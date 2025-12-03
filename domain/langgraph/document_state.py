from typing import TypedDict, List, Optional, Dict, Any
from dataclasses import dataclass


class DocumentState(TypedDict, total=False):
    """
    LangGraph 워크플로우 상태
    
    워크플로우 단계:
    1. DataLoader: code_change_id로 DB에서 데이터 로드
    2. ChangeAnalyzer: diff를 LLM으로 분석
    3. DocumentDecider: 기존 문서 업데이트 vs 신규 생성 결정
    4. DocumentGenerator: 문서 생성 또는 업데이트
    5. DocumentSaver: DB에 저장 (draft 상태)
    """
    
    # 입력 데이터
    code_change_id: int  # CodeChange ID (필수 입력)
    
    # 로드된 데이터
    code_change: Optional[Dict[str, Any]]  # CodeChange 정보 (commit_sha, message, timestamp )
    file_changes: Optional[List[Dict[str, Any]]]  # FileChange 목록 (filename, status, patch )
    diff_content: Optional[str]  # 통합된 diff 내용
    changed_files: Optional[List[str]]  # 변경된 파일명 목록
    repository_name: Optional[str]  # 저장소 full_name
    access_token: Optional[str]  # GitHub API 액세스 토큰
    
    existing_document: Optional[Dict[str, Any]]  # 기존 문서 (있는 경우)
    # 부분 업데이트를 위한 대상 섹션 목록 (예: ["overview","modules","changelog"]) 
    target_doc_sections: Optional[List[str]]
    
    # 분석 결과
    analysis_result: Optional[str]  # LLM 분석 결과 (변경사항 요약)
    
    # 문서 생성 결정
    should_update: bool  # True: 기존 문서 업데이트, False: 신규 생성
    needs_full_analysis: Optional[bool]  # True: 전체 저장소 분석, False: 변경사항만
    
    # 문서 생성 결과
    document_title: Optional[str]  # 문서 제목
    document_content: Optional[str]  # 생성/업데이트된 문서 본문 (마크다운)
    document_summary: Optional[str]  # 문서 요약
    # 부분 업데이트 결과 메타데이터
    updated_sections: Optional[List[Dict[str, Any]]]
    
    # 저장소 전체 분석 결과 (신규 추가)
    repository_path: Optional[str]  # 다운로드된 저장소 경로
    code_files: Optional[List[Dict[str, Any]]]  # 분석할 코드 파일 목록
    repository_structure: Optional[Dict[str, Any]]  # 저장소 구조 정보
    parsed_files: Optional[List[Dict[str, Any]]]  # Tree-sitter로 파싱된 파일 정보
    file_summaries: Optional[List[Dict[str, Any]]]  # 파일별 요약 결과
    
    # 저장 결과
    document_id: Optional[int]  # 저장된 Document ID
    action: Optional[str]  # "created" 또는 "updated"
    
    # 상태 및 에러
    status: str  # "loading", "analyzing", "analyzing_files", "parsing_files", "summarizing_files", "generating", "saving", "completed", "error"
    error: Optional[str]  # 에러 메시지

    # 실행/환경 관련 옵션
    openai_api_key: Optional[str]
    use_mock: Optional[bool]