from typing import Dict, Any, Optional
import os
from functools import partial

from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END

from .document_state import DocumentState
from .nodes import (
    data_loader_node,
    change_analyzer_node,
    document_decider_node,
    document_generator_node,
    document_saver_node,
    repository_analyzer_node,
    file_parser_node,
    file_summarizer_node,
    full_repository_document_generator_node,
)

#LangGraph 워크플로우 메인 클래스
class DocumentWorkflow:
    """
    문서 자동 생성/업데이트 워크플로우
    
    5개 노드로 구성:
        1. data_loader: DB에서 데이터 로드
        2. change_analyzer: LLM으로 변경사항 분석
        3. document_decider: 업데이트 vs 신규 생성 결정
        4. document_generator: 마크다운 문서 생성
        5. document_saver: DB에 저장
    """
    
    def __init__(self, openai_api_key: Optional[str] = None, use_mock: bool = False):
        """
        Args:
            openai_api_key: OpenAI API 키 (없으면 환경변수에서 가져옴)
            use_mock: True면 LLM 대신 Mock 응답 사용 (테스트/개발용)
        """
        self.use_mock = use_mock
        self.api_key = openai_api_key or os.getenv("OPENAI_API_KEY")
        
        # LLM 초기화
        if not use_mock:
            if not self.api_key:
                raise ValueError("OPENAI_API_KEY is required (or use use_mock=True)")
            
            # 문서/변경 분석용 모델: 환경변수 DOC_GENERATOR_MODEL 사용(기본 gpt-4o)
            generator_model = os.getenv("DOC_GENERATOR_MODEL", "gpt-5")
            # ChatOpenAI: 기존 코드 스타일(api_key) 유지, 모델 환경변수화
            # ChatOpenAI SecretStr 요구를 우회: 래퍼 함수 제공
            def _key_provider() -> str:
                return self.api_key or ""  # None 방지
            self.llm = ChatOpenAI(
                api_key=_key_provider,
                model=generator_model,
                temperature=0.1
            )
        else:
            self.llm = None  # Mock 모드에서는 LLM 사용 안함
        
        # 워크플로우 빌드
        self.workflow = self._build_workflow()
    
    def _build_workflow(self):
        """LangGraph 워크플로우 구성"""
        workflow = StateGraph(DocumentState)
        
        # 노드 추가 (각 노드는 독립적인 파일에서 가져옴)
        workflow.add_node("data_loader", data_loader_node)
        

        workflow.add_node(
            "change_analyzer",
            partial(change_analyzer_node, llm=self.llm, use_mock=self.use_mock)
        )
        
        workflow.add_node("document_decider", document_decider_node)
        
        #저장소 분석 노드 추가
        workflow.add_node(
            "repository_analyzer",
            partial(repository_analyzer_node, use_mock=self.use_mock)
        )
        
        # 파일 파싱 노드 추가
        workflow.add_node(
            "file_parser",
            partial(file_parser_node, use_mock=self.use_mock)
        )
        
        # 파일 요약 노드 추가
        workflow.add_node(
            "file_summarizer",
            partial(file_summarizer_node, use_mock=self.use_mock, openai_api_key=self.api_key)
        )
        
        # 전체 저장소 분석 시에는 새로운 문서 생성기 사용
        workflow.add_node(
            "document_generator",
            partial(document_generator_node, llm=self.llm, use_mock=self.use_mock)
        )
        
        # 전체 저장소 문서 생성 노드 추가
        workflow.add_node(
            "full_repository_document_generator",
            partial(full_repository_document_generator_node, use_mock=self.use_mock, openai_api_key=self.api_key)
        )
        
        workflow.add_node("document_saver", document_saver_node)
        

        
        # 조건부 라우팅 함수: 업데이트 여부에 따라 change_analyzer 실행 결정
        def route_after_decider(state: DocumentState) -> str:
            """기존 문서가 있으면 change_analyzer로, 없으면 바로 repository_analyzer로"""
            if state.get("should_update", False):
                # 기존 문서 업데이트 → 변경사항 분석 필요
                return "change_analyzer"
            else:
                # 신규 문서 생성 → 전체 저장소 분석
                return "repository_analyzer"
        
        # 워크플로우 연결
        workflow.set_entry_point("data_loader")
        workflow.add_edge("data_loader", "document_decider")
        
        # 조건부 분기: 기존 문서 있으면 change_analyzer, 없으면 repository_analyzer
        workflow.add_conditional_edges(
            "document_decider",
            route_after_decider,
            {
                "change_analyzer": "change_analyzer",
                "repository_analyzer": "repository_analyzer"
            }
        )
        
        # change_analyzer 이후에는 document_generator로
        workflow.add_edge("change_analyzer", "document_generator")
        
        # 저장소 분석 → 파일 파싱 → 파일 요약 → 전체 문서 생성
        workflow.add_edge("repository_analyzer", "file_parser")
        workflow.add_edge("file_parser", "file_summarizer")
        workflow.add_edge("file_summarizer", "full_repository_document_generator")
        
        # 일반 문서 생성과 전체 문서 생성 모두 문서 저장으로 연결
        workflow.add_edge("document_generator", "document_saver")
        workflow.add_edge("full_repository_document_generator", "document_saver")
        workflow.add_edge("document_saver", END)
        
        return workflow.compile()
    
    def process(self, code_change_id: int) -> Dict[str, Any]:
        """
        워크플로우 실행
        
        Args:
            code_change_id: CodeChange ID
            
        Returns:
            {
                "success": True/False,
                "document_id": int,
                "action": "created" | "updated",
                "title": str,
                "summary": str,
                "error": str  # 실패 시
            }
        """
        initial_state: DocumentState = {
            "code_change_id": code_change_id,
            "status": "loading",
            "should_update": False,
        }
        
        result = self.workflow.invoke(initial_state)
        
        if result.get("status") == "completed":
            return {
                "success": True,
                "document_id": result.get("document_id"),
                "action": result.get("action"),
                "title": result.get("document_title"),
                "summary": result.get("document_summary"),
            }
        else:
            return {
                "success": False,
                "error": result.get("error", "Unknown error"),
            }
