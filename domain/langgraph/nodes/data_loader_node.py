from typing import TYPE_CHECKING
from ..document_state import DocumentState
from database import SessionLocal
from models import CodeChange, FileChange, Document


def _get_repository_access_token_sync(full_name: str) -> str:
    """저장소의 액세스 토큰 가져오기 (동기 버전)"""
    from models import WebhookRegistration
    
    session = SessionLocal()
    try:
        # 저장소의 웹훅 등록 정보에서 토큰 가져오기
        repo_owner, repo_name = full_name.split("/") if "/" in full_name else (full_name, "")
        webhook_reg = session.query(WebhookRegistration).filter(
            WebhookRegistration.repo_owner == repo_owner,
            WebhookRegistration.repo_name == repo_name,
            WebhookRegistration.is_active == True
        ).first()

        if webhook_reg is not None and webhook_reg.access_token is not None:
            return str(webhook_reg.access_token)
        else:
            print(f"No access token found for repository {full_name}")
            return ""
    except Exception as e:
        print(f"Failed to get access token for {full_name}: {e}")
        return ""
    finally:
        session.close()


if TYPE_CHECKING:
    pass

#DB에서 CodeChange, FileChange, 기존 Document를 로드하는 노드

def data_loader_node(state: DocumentState) -> DocumentState:
    """
    데이터 로더 노드
    
    역할:
        - CodeChange 조회 (커밋 정보)
        - FileChange 목록 조회 (변경된 파일들)
        - Repository 정보 조회
        - 기존 Document 조회 (같은 저장소의 최신 문서)
        - diff_content 통합
    
    입력:
        - code_change_id: 처리할 CodeChange ID
    
    출력:
        - code_change: 커밋 정보 딕셔너리
        - file_changes: FileChange 목록
        - diff_content: 통합된 diff 내용
        - changed_files: 변경된 파일명 목록
        - repository_name: 저장소 이름
        - existing_document: 기존 문서 (있으면)
        - status: "analyzing"
    """
    try:
        code_change_id = state.get("code_change_id")
        if not code_change_id:
            state["error"] = "code_change_id is required"
            state["status"] = "error"
            return state
        session = SessionLocal()
        
        try:
            # CodeChange 조회
            code_change = session.query(CodeChange).filter(
                CodeChange.id == code_change_id
            ).first()
            
            if not code_change:
                state["error"] = f"CodeChange not found: {code_change_id}"
                state["status"] = "error"
                return state
            
            # FileChange 조회
            file_changes = session.query(FileChange).filter(
                FileChange.code_change_id == code_change_id
            ).all()
            
            # Repository 정보
            repository_name = "unknown"
            if code_change.repository:
                repository_name = code_change.repository.full_name
            
            # 기존 문서 조회 (같은 저장소의 최신 문서)
            existing_doc = session.query(Document).filter(
                Document.repository_name == repository_name,
                Document.status.in_(["generated", "edited", "reviewed"])
            ).order_by(Document.updated_at.desc()).first()
            
            # diff 통합
            diff_parts = []
            changed_files = []
            for fc in file_changes:
                changed_files.append(fc.filename)
                diff_parts.append(
                    f"\n### {fc.filename} ({fc.status})\n"
                    f"+{fc.additions} -{fc.deletions}\n\n"
                    f"{fc.patch or '(no patch)'}\n"
                )
            
            diff_content = "\n".join(diff_parts)
            
            # Access token 추출 (저장소 분석에 필요)
            access_token = _get_repository_access_token_sync(repository_name)
            
            # State 업데이트
            state["code_change"] = {
                "id": code_change.id,
                "commit_sha": code_change.commit_sha,
                "commit_message": code_change.commit_message,
                "author": code_change.author_name,
                "timestamp": code_change.timestamp.isoformat() if code_change.timestamp is not None else None,
            }
            state["access_token"] = access_token
            state["file_changes"] = [
                {
                    "filename": fc.filename,
                    "status": fc.status,
                    "changes": fc.changes,
                    "additions": fc.additions,
                    "deletions": fc.deletions,
                    "patch": fc.patch,
                }
                for fc in file_changes
            ]
            state["diff_content"] = diff_content
            state["changed_files"] = changed_files
            state["repository_name"] = repository_name
            
            if existing_doc:
                state["existing_document"] = {
                    "id": existing_doc.id,
                    "title": existing_doc.title,
                    "content": existing_doc.content,
                    "summary": existing_doc.summary,
                }
            else:
                state["existing_document"] = None
            
            state["status"] = "analyzing"
            return state
            
        finally:
            session.close()
            
    except Exception as e:
        state["error"] = f"Data loader failed: {str(e)}"
        state["status"] = "error"
        return state
