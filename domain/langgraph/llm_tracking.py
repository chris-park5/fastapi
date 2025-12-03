import json
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional

try:
    from langchain.callbacks import get_openai_callback  # 최신 LangChain
except ImportError:  # 호환성 처리
    from langchain_community.callbacks import get_openai_callback  # type: ignore

from app.logging_config import get_logger  # 로깅 재사용

_usage_logger = get_logger("llm")


LOG_DIR = Path("logs")
LOG_FILE = LOG_DIR / "llm_usage.log"
LOG_DIR.mkdir(exist_ok=True)


def _write_json_line(data: dict) -> None:
    """사용량 데이터를 JSONL 형태로 파일에 기록"""
    try:
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False) + "\n")
    except Exception as e:
        _usage_logger.error(f"Failed to write LLM usage log: {e}")


@contextmanager
def track_llm_usage(operation: str, llm_model: Optional[str] = None) -> Generator:
    """
    LLM 호출 사용량 추적 컨텍스트 매니저.

    사용 예:
        with track_llm_usage("project_overview", llm_model="gpt-4o"):
            response = llm.invoke(messages)

    Args:
        operation: 논리적 작업명 (예: 'project_overview', 'architecture', 'key_modules')
        llm_model: 사용한 모델명 (선택)
    Yields:
        OpenAI 콜백 객체 (토큰/비용 정보 접근)
    """
    start = time.time()
    with get_openai_callback() as cb:  # 토큰/비용 자동 집계
        yield cb
    duration = time.time() - start

    usage_record = {
        "operation": operation,
        "model": llm_model,
        "prompt_tokens": getattr(cb, "prompt_tokens", None),
        "completion_tokens": getattr(cb, "completion_tokens", None),
        "total_tokens": getattr(cb, "total_tokens", None),
        "total_cost_usd": getattr(cb, "total_cost", None),  # 달러 단위
        "successful_requests": getattr(cb, "successful_requests", None),
        "duration_sec": round(duration, 3),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")
    }

    _usage_logger.info(
        f"LLM usage recorded ({operation})",
        extra={k: v for k, v in usage_record.items() if v is not None}
    )
    _write_json_line(usage_record)


def summarize_usage(limit: int = 1000) -> dict:
    """최근 사용량 로그를 읽어 간단 요약 반환"""
    if not LOG_FILE.exists():
        return {"total_calls": 0, "total_tokens": 0, "approx_cost_usd": 0.0}

    total_calls = 0
    total_tokens = 0
    total_cost = 0.0
    try:
        with LOG_FILE.open("r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i >= limit:
                    break
                try:
                    data = json.loads(line)
                    total_calls += 1
                    total_tokens += data.get("total_tokens", 0) or 0
                    total_cost += data.get("total_cost_usd", 0.0) or 0.0
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        _usage_logger.error(f"Failed to summarize LLM usage: {e}")
    return {
        "total_calls": total_calls,
        "total_tokens": total_tokens,
        "approx_cost_usd": round(total_cost, 4)
    }


__all__ = ["track_llm_usage", "summarize_usage"]