@router.post("/new-session", response_model=NewSessionResponse)
async def new_session():
    """새로운 대화 세션 시작"""
    session_id = get_or_create_session(None)
    return NewSessionResponse(
        session_id=session_id,
        message="새로운 대화가 시작되었습니다."
    )

@router.delete("/{session_id}")
async def delete_session(session_id: str):
    """특정 세션 삭제"""
    if session_id in conversation_store:
        del conversation_store[session_id]
        return {"message": "세션이 삭제되었습니다."}
    else:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")