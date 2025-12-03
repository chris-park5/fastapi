"""
File Summarizer Node - LLM 기반 파일 요약 생성
"""

import json
import os
from typing import Dict, List, Optional, Any, Callable
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import threading

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from ..document_state import DocumentState


# ============================================================
# Config & Utility
# ============================================================

class FileSummarizerConfig:
    """Summarizer 관련 환경 설정"""
    DEFAULT_MODEL = os.getenv("DOC_SUMMARIZER_MODEL", "gpt-5")
    SUMMARY_LIMIT = int(os.getenv("FILE_SUMMARY_LIMIT", "30"))

    @staticmethod
    def limit_files(files: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """파일 개수 제한 적용"""
        if len(files) > FileSummarizerConfig.SUMMARY_LIMIT > 0:
            print(
                f"[FileSummarizer] Limiting {len(files)} → {FileSummarizerConfig.SUMMARY_LIMIT}"
            )
            return files[:FileSummarizerConfig.SUMMARY_LIMIT]
        return files


def set_error(state: DocumentState, message: str) -> DocumentState:
    state["error"] = message
    state["status"] = "error"
    return state


# ============================================================
# Main Node
# ============================================================

INCLUDE_FULL_CODE = os.getenv("FILE_SUMMARY_INCLUDE_FULL_CODE", "false").lower() in {"1", "true", "yes"}
MAX_CODE_CHARS = int(os.getenv("FILE_SUMMARY_MAX_CODE_CHARS", "15000"))


def file_summarizer_node(
    state: DocumentState,
    use_mock: bool = False,
    openai_api_key: Optional[str] = None,
    include_full_code: Optional[bool] = None,
) -> DocumentState:

    parsed_files = state.get("parsed_files")
    if not parsed_files:
        return set_error(state, "No parsed_files to summarize")

    parsed_files = FileSummarizerConfig.limit_files(parsed_files)
    repository_path = str(state.get("repository_path", "") or "")

    print(f"[FileSummarizer] Target files: {len(parsed_files)}")

    # --- Decide Strategy ---
    # include_full_code 우선 순위: 함수 인자 > 환경변수 > False
    use_full_code = include_full_code if include_full_code is not None else INCLUDE_FULL_CODE

    summarizer = _get_summarizer_strategy(use_mock, openai_api_key, use_full_code)

    # 병렬 처리 설정
    max_workers = int(os.getenv("FILE_SUMMARIZER_MAX_CONCURRENCY", "4"))
    max_workers = max(1, max_workers)

    file_summaries = []
    
    def _process_file(idx: int, file_info: Dict[str, Any]) -> Dict[str, Any]:
        thread_id = threading.current_thread().name
        file_path = file_info.get('file_path', 'unknown')
        start = time.time()
        print(f"  [{thread_id}] 시작: {idx}/{len(parsed_files)} - {file_path}")
        
        summary = summarizer(file_info, repository_path)
        
        elapsed = time.time() - start
        print(f"  [{thread_id}] 완료: {file_path} ({elapsed:.2f}s)")
        return summary

    if len(parsed_files) > 1 and max_workers > 1 and not use_mock:
        workers = min(max_workers, len(parsed_files))
        print(f"[파일 요약 병렬 처리] {len(parsed_files)}개 파일, {workers}개 워커 사용")
        start_time = time.time()
        
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(_process_file, idx, f): idx for idx, f in enumerate(parsed_files, 1)}
            for fut in as_completed(futures):
                file_summaries.append(fut.result())
        
        elapsed = time.time() - start_time
        print(f"[파일 요약 병렬 완료] {elapsed:.2f}초 소요")
    else:
        print(f"[파일 요약 순차 처리] {len(parsed_files)}개 파일")
        start_time = time.time()
        
        for idx, file_info in enumerate(parsed_files, 1):
            print(f"[FileSummarizer] Summarizing {idx}/{len(parsed_files)}: {file_info.get('file_path')}")
            summary = summarizer(file_info, repository_path)
            file_summaries.append(summary)
        
        elapsed = time.time() - start_time
        print(f"[파일 요약 순차 완료] {elapsed:.2f}초 소요")

    state["file_summaries"] = file_summaries
    state["status"] = "generating_document"

    print(f"[FileSummarizer] Completed: {len(file_summaries)} summaries")
    return state


# ============================================================
# Strategy Selector (Mock / LLM / Fallback)
# ============================================================

def _get_summarizer_strategy(
    use_mock: bool,
    openai_api_key: Optional[str],
    use_full_code: bool
) -> Callable:

    if use_mock:
        return lambda info, repo: _generate_mock_file_summary(info, use_full_code)

    if not openai_api_key:
        print("[FileSummarizer] No API key → switching to mock mode.")
        return lambda info, repo: _generate_mock_file_summary(info, use_full_code)

    # Real LLM strategy
    llm = ChatOpenAI(
        api_key=lambda: openai_api_key,
        model=FileSummarizerConfig.DEFAULT_MODEL,
        temperature=0.1,
    )
    return lambda info, repo: (
        _generate_file_summary_with_llm(info, llm, repo, use_full_code)
        or _generate_fallback_file_summary(info)
    )


# ============================================================
# Mock Summary Generator
# ============================================================

def _generate_mock_file_summary(file_info: Dict[str, Any], use_full_code: bool) -> Dict[str, Any]:
    """Mock 파일 요약 생성"""
    file_path = file_info.get("file_path", "")
    language = file_info.get("language", "")
    functions, classes, imports = (
        file_info.get("functions", []),
        file_info.get("classes", []),
        file_info.get("imports", []),
    )

    file_name = Path(file_path).stem

    mock_patterns = {
        "main": ("애플리케이션의 진입점 역할", "초기화 및 설정 모듈"),
        "model": ("데이터 모델 정의", "스키마 및 ORM 매핑"),
        "schema": ("데이터 구조 정의", "Pydantic 기반 검증"),
        "test": ("테스트 모듈", "테스트 케이스 실행 및 검증"),
        "router": ("API 라우팅 기능", "엔드포인트 관리"),
        "service": ("비즈니스 로직 처리", "서비스 계층 역할"),
    }

    purpose, role = next(
        ((v[0], v[1]) for k, v in mock_patterns.items() if k in file_name.lower()),
        (f"{language.title()} 기능 모듈", "모듈 기능 제공"),
    )

    code_block = None
    if use_full_code and isinstance(file_info.get("full_code"), str):
        raw = file_info["full_code"]
        if len(raw) > MAX_CODE_CHARS:
            raw = raw[:MAX_CODE_CHARS] + "\n... (truncated) ..."
        code_block = raw

    summary = {
        "file_path": file_path,
        "language": language,
        "summary": {
            "purpose": purpose,
            "role": role,
            "key_features": [
                f"{len(functions)}개 함수",
                f"{len(classes)}개 클래스",
                "모듈화된 구조 유지"
            ],
            "complexity_assessment": "보통",
            "dependency_analysis": [f"{len(imports)}개 의존성"],
            "maintainability": "양호",
            "functions_count": len(functions),
            "classes_count": len(classes),
            "imports_count": len(imports),
            "loc": file_info.get("loc", 0)
        },
        "generated_at": "mock",
        "generation_method": "mock",
        "included_full_code": bool(code_block),
        "full_code": code_block,
    }

    return summary


# ============================================================
# LLM-based Summary Generator
# ============================================================

def _generate_file_summary_with_llm(
    file_info: Dict[str, Any],
    llm: ChatOpenAI,
    repository_path: str,
    use_full_code: bool,
) -> Optional[Dict[str, Any]]:

    try:
        file_path = file_info.get("file_path", "")
        preview = _get_file_content_preview(file_info, repository_path, use_full_code)

        system_prompt = _build_system_prompt(file_info)
        user_prompt = _build_user_prompt(file_info, preview)

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]

        response = llm.invoke(messages)
        text = _extract_text(response.content)

        json_block = _extract_json(text)
        data = json.loads(json_block)

        return {
            "file_path": file_path,
            "language": file_info.get("language", ""),
            "summary": {
                **data,
                "functions_count": len(file_info.get("functions", [])),
                "classes_count": len(file_info.get("classes", [])),
                "imports_count": len(file_info.get("imports", [])),
                "loc": file_info.get("loc", 0),
            },
            "generated_at": "llm",
            "generation_method": "llm",
            "included_full_code": use_full_code and isinstance(file_info.get("full_code"), str)
            #"full_code": file_info.get("full_code") if use_full_code else None,
        }

    except Exception as e:
        print(f"[FileSummarizer] LLM failure for {file_info.get('file_path')}: {e}")
        return None


# ============================================================
# Fallback Summary
# ============================================================

def _generate_fallback_file_summary(file_info: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "file_path": file_info.get("file_path"),
        "language": file_info.get("language"),
        "summary": {
            "purpose": "언어 기반 기본 소스 파일",
            "role": "구현 및 기능 제공",
            "key_features": [
                f"{len(file_info.get('functions', []))}개 함수",
                f"{len(file_info.get('classes', []))}개 클래스",
            ],
            "complexity_assessment": "분석 실패",
            "dependency_analysis": ["자동 분석 실패"],
            "maintainability": "검토 필요",
            "functions_count": len(file_info.get("functions", [])),
            "classes_count": len(file_info.get("classes", [])),
            "imports_count": len(file_info.get("imports", [])),
            "loc": file_info.get("loc", 0)
        },
        "generated_at": "fallback",
        "generation_method": "fallback"
    }


# ============================================================
# Prompt Builders & Helpers
# ============================================================

def _build_system_prompt(file_info: Dict[str, Any]) -> str:
    return f"""
당신은 대규모 소프트웨어 리포지토리 분석 전문가입니다.
주어진 파일 정보를 기반으로 다음 JSON 스키마에 맞는 파일 요약을 생성하세요.
모든 필드를 반드시 포함하고, 알 수 없는 정보는 'unknown' 또는 빈 배열로 처리하세요.

파일: {file_info.get("file_path")}
언어: {file_info.get("language")}
라인 수: {file_info.get("loc")}
복잡도: {file_info.get("complexity_score")}

JSON 스키마:
{{
  "file_path": "",
  "directory": "",
  "file_name": "",
  "language": "",
  "loc": 0,
  "complexity_score": 0,
  "module_type": "controller | service | model | util | view | router | config | test | script | core | unknown",
  "responsibility": "",
  "summary": "",
  "key_features": [],
  "exports": [],
  "functions": [],
  "classes": [],
  "imports": [],
  "dependencies": {{"internal": [], "external": []}},
  "architecture_role": {{"layer": "presentation | application | domain | infrastructure | unknown", "upstream": [], "downstream": [], "data_flow": ""}},
  "api_endpoints": [],
  "model_schema": {{"fields": []}},
  "tests": []
}}
"""

def _build_user_prompt(file_info: Dict[str, Any], preview: str) -> str:
    return f"""
함수 목록:
{file_info.get("functions", [])}

클래스 목록:
{file_info.get("classes", [])}

임포트:
{file_info.get("imports", [])}

파일 내용 미리보기:
{preview}

지침:
1. 모듈 타입(module_type)은 파일의 역할을 가장 잘 나타내는 한 가지를 선택하세요.
2. responsibility, summary, key_features를 작성해 파일의 핵심 기능과 역할을 명확히 기술하세요.
3. architecture_role의 layer, upstream/downstream, data_flow를 가능한 범위 내에서 추론하세요.
4. exports, functions, classes는 실제 코드 구조 기반으로 작성하세요.
5. api_endpoints, model_schema, tests는 관련 파일인 경우만 작성하고, 없으면 빈 배열로 처리하세요.

위 정보를 기반으로 JSON 형식으로 파일 요약을 생성하세요.
"""



def _extract_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(c for c in content if isinstance(c, str))
    return str(content)


def _extract_json(text: str) -> str:
    if "```json" in text:
        start = text.find("```json") + 7
        end = text.find("```", start)
        return text[start:end].strip()
    if "```" in text:
        start = text.find("```") + 3
        end = text.find("```", start)
        return text[start:end].strip()
    return text


def _get_file_content_preview(file_info: Dict[str, Any], repo: str, use_full_code: bool) -> str:
    if use_full_code and isinstance(file_info.get("full_code"), str):
        raw = file_info["full_code"]
        if len(raw) > MAX_CODE_CHARS:
            raw = raw[:MAX_CODE_CHARS] + "\n... (truncated) ..."
        return raw

    preview = file_info.get("full_code")
    if preview:
        return preview[:500]

    path = Path(repo) / file_info.get("file_path", "")
    if path.exists():
        try:
            content = path.read_text(errors="ignore")
        except Exception:
            return "<read error>"
        return content[:500]

    return "<no preview available>"
