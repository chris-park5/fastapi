@router.post("/", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    try:
        # 세션 가져오기 또는 생성
        session_id = get_or_create_session(request.session_id)

        # 사용자 메시지를 대화 히스토리에 추가
        conversation_store[session_id]['messages'].append({
            "role": "user",
            "content": request.message
        })

        conversation_store[session_id]['messages'][0]["content"] = request.system_message

        # OpenAI API 호출
        response = openai.ChatCompletion.create(
            model=MODEL,
            messages=conversation_store[session_id]['messages']
        )
        assistant_response = response['choices'][0]['message']['content']

        # 어시스턴트 응답을 대화 히스토리에 추가
        conversation_store[session_id]['messages'].append({
            "role": "assistant",
            "content": assistant_response
        })

        # 대화 히스토리가 너무 길어지면 최근 대화만 유지 (시스템 메시지 + 최근 20턴)
        if len(conversation_store[session_id]['messages']) > 41:
            system_msg = conversation_store[session_id]['messages'][0]
            recent_messages = conversation_store[session_id]['messages'][-40:]
            conversation_store[session_id]['messages'] = [system_msg] + recent_messages
        return ChatResponse(response=assistant_response, session_id=session_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))