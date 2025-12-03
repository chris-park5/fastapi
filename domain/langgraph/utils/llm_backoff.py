import os
import time
import random
from typing import Any, Sequence
from langchain_core.messages import BaseMessage

# 간단한 레이트리밋 / 일시적 오류 재시도 유틸
# LangChain OpenAI ChatOpenAI.invoke 호출을 감싸 사용
# 환경변수:
#   LLM_MAX_RETRIES (기본 3)
#   LLM_BASE_BACKOFF_SECONDS (기본 1)
#   LLM_MAX_BACKOFF_SECONDS (기본 10)
#   LLM_RETRYABLE_ERROR_SUBSTRINGS (쉼표구분, 기본: 'rate limit,timeout,overloaded,429')
# 실패 시 마지막 예외를 다시 raise

RETRYABLE_DEFAULT = ["rate limit", "timeout", "overloaded", "429"]


def _is_retryable_error(err: Exception) -> bool:
    txt = str(err).lower()
    extra = os.getenv("LLM_RETRYABLE_ERROR_SUBSTRINGS", "")
    tokens = [t.strip().lower() for t in extra.split(',') if t.strip()] or []
    for key in RETRYABLE_DEFAULT + tokens:
        if key in txt:
            return True
    return False


def invoke_with_retry(llm: Any, messages: Sequence[BaseMessage]) -> Any:
    max_retries = int(os.getenv("LLM_MAX_RETRIES", "3"))
    base = float(os.getenv("LLM_BASE_BACKOFF_SECONDS", "1"))
    max_backoff = float(os.getenv("LLM_MAX_BACKOFF_SECONDS", "10"))

    attempt = 0
    while True:
        try:
            return llm.invoke(messages)
        except Exception as e:  # Broad catch; refine if needed
            attempt += 1
            if attempt > max_retries or not _is_retryable_error(e):
                raise
            delay = min(max_backoff, base * (2 ** (attempt - 1)))
            # Jitter: 0.8 ~ 1.3배
            delay *= random.uniform(0.8, 1.3)
            time.sleep(delay)

