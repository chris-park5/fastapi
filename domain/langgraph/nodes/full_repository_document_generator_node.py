"""
Full Repository Document Generator Node
전체 저장소 문서를 생성하는 LangGraph 노드
"""

import json
from typing import Dict, List, Optional, Any
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from ..document_state import DocumentState
from ..utils.llm_backoff import invoke_with_retry


# ============================================================
#  LLM Wrapper – LLM 호출 담당
# ============================================================
class FullRepoDocumentLLM:
    """LLM 기반 문서 생성 기능 캡슐화 (버전별 프롬프트 지원)"""

    def __init__(self, api_key: str, prompt_version: str):
        self._init_env(api_key)
        self.llm = ChatOpenAI(model="gpt-5", temperature=0.2)
        # 프롬프트 세트 로딩
        from .prompts import get_prompt_set
        self.prompt_version = prompt_version
        self.prompt_set = get_prompt_set(prompt_version)

    @staticmethod
    def _init_env(api_key: str):
        import os
        os.environ["OPENAI_API_KEY"] = api_key

    @staticmethod
    def _normalize_content(response: Any) -> str:
        content = getattr(response, "content", "")
        if isinstance(content, list):
            parts: List[str] = []
            for part in content:
                if isinstance(part, str):
                    parts.append(part)
                else:
                    try:
                        parts.append(json.dumps(part, ensure_ascii=False))
                    except Exception:
                        parts.append(str(part))
            content = " "+" ".join(parts) if parts else ""
        return str(content).strip()

    def generate_overview(self, files, structure, repo_name) -> str:
        import time, threading
        tname = threading.current_thread().name
        start = time.time()
        print(f"  [{tname}] Section 'overview' 시작")
        system_prompt, builder = self.prompt_set["overview"]
        human_prompt = builder(files, structure, repo_name)
        messages = [SystemMessage(content=system_prompt), HumanMessage(content=human_prompt)]
        resp = invoke_with_retry(self.llm, messages)
        out = self._normalize_content(resp)
        print(f"  [{tname}] Section 'overview' 완료 ({time.time()-start:.2f}s)")
        return out

    def generate_architecture(self, files, structure, repo_name) -> str:
        import time, threading
        tname = threading.current_thread().name
        start = time.time()
        print(f"  [{tname}] Section 'architecture' 시작")
        system_prompt, builder = self.prompt_set["architecture"]
        human_prompt = builder(files, structure, repo_name)
        messages = [SystemMessage(content=system_prompt), HumanMessage(content=human_prompt)]
        resp = invoke_with_retry(self.llm, messages)
        out = self._normalize_content(resp)
        print(f"  [{tname}] Section 'architecture' 완료 ({time.time()-start:.2f}s)")
        return out

    def generate_key_modules(self, files, structure, repo_name) -> str:
        import time, threading
        tname = threading.current_thread().name
        start = time.time()
        print(f"  [{tname}] Section 'modules' 시작")
        system_prompt, builder = self.prompt_set["modules"]
        human_prompt = builder(files, structure, repo_name)
        messages = [SystemMessage(content=system_prompt), HumanMessage(content=human_prompt)]
        resp = invoke_with_retry(self.llm, messages)
        out = self._normalize_content(resp)
        print(f"  [{tname}] Section 'modules' 완료 ({time.time()-start:.2f}s)")
        return out


# ============================================================
#  Mock Builder – Mock 문서 생성 담당
# ============================================================
class FullRepoMockBuilder:
    """Mock 문서 생성 전용 클래스"""

    def __init__(self, file_summaries, repository_structure, repository_name):
        self.fs = file_summaries
        self.struct = repository_structure
        self.name = repository_name

    def build(self) -> Dict[str, str]:
        stats = self._collect_stats()
        modules = self._extract_key_modules()

        content = self._render(stats, modules)
        summary = self._summary(stats)

        return {
            "title": f"{self.name} - Project Documentation",
            "content": content,
            "summary": summary,
        }

    # ---------- 내부 처리 ----------
    def _collect_stats(self):
        return {
            "total_files": len(self.fs),
            "total_functions": sum(f.get("summary", {}).get("functions_count", 0) for f in self.fs),
            "total_classes": sum(f.get("summary", {}).get("classes_count", 0) for f in self.fs),
            "total_loc": sum(f.get("summary", {}).get("loc", 0) for f in self.fs),
            "languages": self._collect_languages(),
        }

    def _collect_languages(self):
        langs = {}
        for fs in self.fs:
            lang = fs.get("language", "unknown")
            langs[lang] = langs.get(lang, 0) + 1
        return langs

    def _extract_key_modules(self):
        result = []
        for fs in self.fs:
            path = fs.get("file_path", "").lower()
            summary = fs.get("summary", {})

            def add(name, t):
                result.append({
                    "name": Path(fs["file_path"]).stem,
                    "type": t,
                    "description": summary.get("purpose", "")
                })

            if any(k in path for k in ["main", "app", "server", "index"]):
                add(path, "Entry Point")
            elif any(k in path for k in ["service", "controller", "handler"]):
                add(path, "Business Logic")
            elif any(k in path for k in ["model", "entity", "schema"]):
                add(path, "Data Model")

        return result[:8]

    def _render(self, stats, modules):
        # 가독성 위해 별도 템플릿 함수로 분리 가능
        languages = ", ".join(stats["languages"].keys())
        primary_lang = max(stats["languages"], key=lambda x: stats["languages"][x])

        return f"""
# {self.name} - Project Documentation

## Project Overview
- Total Files: {stats['total_files']}
- Functions: {stats['total_functions']}
- Classes: {stats['total_classes']}
- LOC: {stats['total_loc']}
- Languages: {languages}
- Primary Language: {primary_lang}

## Key Modules
""" + "\n".join([f"- {m['name']} ({m['type']})" for m in modules]) + """

---
*Generated by Mock Document Builder*
"""

    def _summary(self, stats):
        return (
            f"{self.name} 프로젝트 문서 - {stats['total_files']}개 파일, "
            f"{stats['total_functions']}개 함수, {stats['total_classes']}개 클래스"
        )


# ============================================================
#  Document Builder – Final Document 조합 담당
# ============================================================
class FullRepoDocumentBuilder:
    """문서 섹션을 조합하는 Builder"""

    def __init__(self, repo_name: str):
        self.repo = repo_name
        self.sections = {}

    def add(self, key: str, section: str):
        self.sections[key] = section

    def build(self, file_summaries) -> Dict[str, str]:
        content = f"# {self.repo} - Project Documentation\n\n"

        if "overview" in self.sections:
            content += "## Project Overview\n" + self.sections["overview"] + "\n\n"

        if "architecture" in self.sections:
            content += "## Architecture\n" + self.sections["architecture"] + "\n\n"

        if "modules" in self.sections:
            content += "## Key Modules\n" + self.sections["modules"] + "\n\n"

        summary = f"{self.repo} 프로젝트 문서 - 총 {len(file_summaries)}개 파일 요약 포함"

        return {"content": content, "summary": summary}


# ============================================================
#  Node Function – Orchestration Only
# ============================================================
def full_repository_document_generator_node(
    state: DocumentState,
    use_mock: bool = False,
    openai_api_key: Optional[str] = None,
    prompt_version: Optional[str] = None,
) -> DocumentState:
    """전체 저장소 문서를 생성하는 LangGraph Node"""

    file_summaries: List[Dict[str, Any]] = state.get("file_summaries") or []
    repo_struct: Dict[str, Any] = state.get("repository_structure") or {}
    repo_name: str = state.get("repository_name") or "Unknown Project"

    print(f"[FullRepoDocGen] Starting document generation for: {repo_name}")
    print(f"[FullRepoDocGen] use_mock={use_mock}, has_api_key={bool(openai_api_key)}")
    print(f"[FullRepoDocGen] file_summaries count: {len(file_summaries)}")

    if not file_summaries:
        state["status"] = "error"
        state["error"] = "file_summaries is empty"
        print("[FullRepoDocGen] ERROR: file_summaries is empty")
        return state

    # ───────────────────────────────────────────────
    # MOCK MODE
    # ───────────────────────────────────────────────
    if use_mock or not openai_api_key:
        print("[FullRepoDocGen] Using MOCK mode")
        try:
            builder = FullRepoMockBuilder(file_summaries, repo_struct, repo_name)
            mock_doc = builder.build()

            state["document_title"] = mock_doc["title"]
            state["document_content"] = mock_doc["content"]
            state["document_summary"] = mock_doc["summary"]
            state["status"] = "saving_document"
            print("[FullRepoDocGen] MOCK document generated successfully")
            return state
        except Exception as e:
            print(f"[FullRepoDocGen] MOCK generation failed: {e}")
            state["status"] = "error"
            state["error"] = f"Mock document generation failed: {e}"
            return state

    # ───────────────────────────────────────────────
    # REAL LLM MODE
    # ───────────────────────────────────────────────
    print("[FullRepoDocGen] Using REAL LLM mode")
    # 프롬프트 버전: 파라미터 > 환경변수 > 기본값
    import os
    effective_version = prompt_version or os.getenv("DOCUMENT_PROMPT_VERSION") or "v4"
    print(f"[FullRepoDocGen] Prompt version: {effective_version}")
    
    try:
        print("[FullRepoDocGen] Initializing LLM...")
        llm = FullRepoDocumentLLM(openai_api_key, effective_version)
        doc_builder = FullRepoDocumentBuilder(repo_name)

        # 병렬로 각 섹션 생성 (환경변수 FULL_DOC_MAX_CONCURRENCY)
        max_workers = int(os.getenv("FULL_DOC_MAX_CONCURRENCY", "3"))
        max_workers = max(1, min(max_workers, 3))
        tasks = [
            ("overview", llm.generate_overview, (file_summaries, repo_struct, repo_name)),
            ("architecture", llm.generate_architecture, (file_summaries, repo_struct, repo_name)),
            ("modules", llm.generate_key_modules, (file_summaries, repo_struct, repo_name)),
        ]

        results: Dict[str, str] = {}
        if max_workers > 1:
            print(f"[FullRepoDocGen] Generating sections in parallel (workers={max_workers})")
            with ThreadPoolExecutor(max_workers=max_workers) as ex:
                futures = {ex.submit(func, *args): key for key, func, args in tasks}
                for fut in as_completed(futures):
                    key = futures[fut]
                    try:
                        results[key] = fut.result()
                        print(f"[FullRepoDocGen] Section '{key}' generated")
                    except Exception as se:
                        print(f"[FullRepoDocGen] Section '{key}' failed: {se}")
                        results[key] = ""
        else:
            print("[FullRepoDocGen] Generating sections sequentially")
            for key, func, args in tasks:
                print(f"[FullRepoDocGen] Generating {key}...")
                try:
                    results[key] = func(*args)
                except Exception as se:
                    print(f"[FullRepoDocGen] Section '{key}' failed: {se}")
                    results[key] = ""

        doc_builder.add("overview", results.get("overview", ""))
        doc_builder.add("architecture", results.get("architecture", ""))
        doc_builder.add("modules", results.get("modules", ""))

        result = doc_builder.build(file_summaries)

        state["document_title"] = f"{repo_name} - Project Documentation"
        state["document_content"] = result["content"]
        # 프롬프트 버전 메타정보를 summary 끝에 포함
        state["document_summary"] = result["summary"] + f" (prompt_version={effective_version})"
        state["status"] = "saving_document"
        print("[FullRepoDocGen] LLM document generated successfully")
        return state

    except Exception as e:
        print(f"[FullRepoDocGen] LLM generation failed: {e}")
        import traceback
        traceback.print_exc()
        state["status"] = "error"
        state["error"] = f"Full document generation failed: {e}"
        return state
