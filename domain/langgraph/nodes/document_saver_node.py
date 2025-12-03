from datetime import datetime
from database import SessionLocal
from models import Document

from ..document_state import DocumentState

#생성/업데이트된 문서를 DB에 저장하는 노드

def document_saver_node(state: DocumentState) -> DocumentState:
    """
    문서 저장 노드
    
    역할:
        - 문서를 DB에 저장
        - 업데이트 또는 신규 생성
        - status를 "generated"로 설정
    
    입력:
        - should_update: 업데이트 여부
        - document_content: 문서 내용
        - document_summary: 문서 요약
        - document_title: 문서 제목
        - code_change_id: CodeChange ID
        - code_change: 커밋 정보
        - repository_name: 저장소 이름
        - existing_document: 기존 문서 (업데이트 시)
    
    출력:
        - document_id: 저장된 Document ID
        - action: "created" 또는 "updated"
        - status: "completed"
    
    로직:
        - should_update == True:
            * 기존 Document 업데이트
            * content, summary, status, updated_at 갱신
        - should_update == False:
            * 새 Document 생성
            * status = "generated"
            * document_type = "auto"
    """
    try:
        # 문서 본문이 없다면 저장을 진행할 수 없으므로 바로 실패 처리
        document_content = state.get("document_content")
        document_summary = state.get("document_summary")
        if not document_content:
            state["status"] = "error"
            state["error"] = "Document content missing before save"
            return state
        if document_summary is None:
            state["status"] = "error"
            state["error"] = "Document summary missing before save"
            return state

        session = SessionLocal()
        
        try:
            should_update = state.get("should_update", False)
            code_change_id = state.get("code_change_id")
            if code_change_id is None:
                raise ValueError("code_change_id missing before save")
            code_change = state.get("code_change", {})
            commit_sha = code_change.get("commit_sha", "") if code_change else ""
            
            if should_update:
                # 기존 문서 업데이트
                existing_doc = state.get("existing_document", {})
                doc_id = existing_doc.get("id") if existing_doc else None
                
                if not doc_id:
                    raise ValueError("Document ID not found for update")
                
                document = session.query(Document).filter(Document.id == doc_id).first()
                
                if not document:
                    raise ValueError(f"Document not found: {doc_id}")
                
                # 문서 업데이트
                setattr(document, "content", document_content)
                setattr(document, "summary", document_summary)
                setattr(document, "status", "generated")
                setattr(document, "updated_at", datetime.utcnow())
                
                state["document_id"] = int(getattr(document, "id"))
                state["action"] = "updated"
                    
            else:
                # 신규 문서 생성
                document_title = state.get("document_title")
                if not document_title:
                    raise ValueError("Document title missing before save")

                document = Document(
                    title=document_title,
                    content=document_content,
                    summary=document_summary,
                    status="generated",
                    document_type="auto",
                    commit_sha=commit_sha,
                    repository_name=state.get("repository_name"),
                    code_change_id=code_change_id,
                    generation_metadata={
                        "analysis_result": state.get("analysis_result"),
                        "changed_files": state.get("changed_files"),
                    }
                )
                session.add(document)
                session.flush()
                
                state["document_id"] = int(getattr(document, "id"))
                state["action"] = "created"
            
            session.commit()
            state["status"] = "completed"
            return state
            
        finally:
            session.close()
            
    except Exception as e:
        state["error"] = f"Document saver failed: {str(e)}"
        state["status"] = "error"
        return state
