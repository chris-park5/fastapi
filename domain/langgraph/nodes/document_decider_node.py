from ..document_state import DocumentState

#기존 문서 업데이트 또는 신규 생성을 결정하는 노드

def document_decider_node(state: DocumentState) -> DocumentState:
    """
    문서 결정 노드
    
    역할:
        - 기존 문서 존재 여부 확인
        - 업데이트 또는 신규 생성 결정
        - 문서 제목 설정
        - 전체 저장소 문서 vs 변경사항 문서 결정
    
    입력:
        - existing_document: 기존 문서 정보 (있으면)
        - repository_name: 저장소 이름
        - code_change: 커밋 정보
    
    출력:
        - should_update: True (업데이트) / False (신규 생성)
        - document_title: 문서 제목
        - needs_full_analysis: True (전체 저장소 분석 필요) / False (변경사항만)
    
    로직:
        - existing_document가 있으면:
            * should_update = True
            * 기존 제목 유지
            * needs_full_analysis = False (변경사항만 추가)
        - existing_document가 없으면:
            * should_update = False
            * needs_full_analysis = True (전체 저장소 문서 생성)
            * 새 제목 생성: "{repo_name} - Project Documentation"
    """
    try:
        existing_doc = state.get("existing_document")
        repo_name = state.get("repository_name", "unknown")
        
        if existing_doc:
            # 기존 문서 업데이트 (변경사항만 추가)
            state["should_update"] = True
            state["document_title"] = existing_doc["title"]  # 기존 제목 유지
            state["needs_full_analysis"] = False
            
            print(f"[DocumentDecider] Updating existing document: {existing_doc['title']}")
        else:
            # 신규 문서 생성 (전체 저장소 분석 필요)
            state["should_update"] = False
            state["needs_full_analysis"] = True
            
            # 전체 저장소 문서 제목 생성
            state["document_title"] = f"{repo_name} - Project Documentation"
            
            print(f"[DocumentDecider] Creating new full repository document for: {repo_name}")
        
        return state
        
    except Exception as e:
        state["error"] = f"Document decider failed: {str(e)}"
        state["status"] = "error"
        return state
