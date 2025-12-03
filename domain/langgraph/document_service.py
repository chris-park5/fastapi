from typing import Dict, Any, Optional
import os
from .document_workflow import DocumentWorkflow


class DocumentService:
    """문서 자동 생성/업데이트 서비스"""
    
    def __init__(self, openai_api_key: Optional[str] = None, use_mock: bool = False):
        """
        Args:
            openai_api_key: OpenAI API 키
            use_mock: True면 LLM 대신 Mock 응답 사용 (테스트/개발용)
        """
        self.openai_api_key = openai_api_key or os.getenv("OPENAI_API_KEY")
        self.use_mock = use_mock
    
    async def process_code_change(self, code_change_id: int) -> Dict[str, Any]:
        """
        코드 변경사항을 처리하여 문서 생성/업데이트
        
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
        try:
            workflow = DocumentWorkflow(
                openai_api_key=self.openai_api_key,
                use_mock=self.use_mock
            )
            result = workflow.process(code_change_id)
            return result
            
        except Exception as e:
            return {
                "success": False,
                "error": f"Document service failed: {str(e)}"
            }


# 싱글톤 인스턴스
_service_instance = None


def get_document_service(use_mock: bool = False, openai_api_key: Optional[str] = None) -> DocumentService:
    """
    문서 서비스 인스턴스 반환
    
    Args:
        use_mock: Mock 사용 여부 - True면 OpenAI API 없이 테스트 가능
        openai_api_key: OpenAI API 키
        
    Returns:
        DocumentService 인스턴스
    """
    global _service_instance
    
    if _service_instance is None or openai_api_key or use_mock:
        _service_instance = DocumentService(
            openai_api_key=openai_api_key,
            use_mock=use_mock
        )
    
    return _service_instance
