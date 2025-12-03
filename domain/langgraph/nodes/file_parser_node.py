"""
File Parser 노드 (경량 오케스트레이터)

목표: 파일 파싱 로직을 모듈로 위임하여 유지보수성과 가독성을 향상.
- Tree-sitter 사용 가능 시 우선 사용, 불가하면 언어별 Fallback으로 파싱
- Mock 모드 제공
"""
import os
from typing import Dict, Any

FULL_CODE_LIMIT = int(os.getenv("FILE_PARSER_FULL_CODE_LIMIT", "30000"))  # bytes/characters threshold

from ..document_state import DocumentState
from .parser.tree_sitter_parser import parse_with_best_effort
from .parser.mock_parser import generate_mock_parsing_result


def file_parser_node(state: DocumentState, use_mock: bool = False) -> DocumentState:
    try:
        code_files = state.get("code_files", [])
        repository_path = str(state.get("repository_path") or "")

        if not code_files:
            state["error"] = "No code files to parse"
            state["status"] = "error"
            return state

        print(f"[FileParser] Parsing {len(code_files)} files...")

        if use_mock:
            parsed_files = [generate_mock_parsing_result(fi) for fi in code_files]
            state["parsed_files"] = parsed_files
            state["status"] = "summarizing_files"
            print(f"[FileParser] Mock parsing completed for {len(parsed_files)} files")
            return state

        parsed_files = []
        for file_info in code_files:
            try:
                lang = _resolve_language(file_info)
                rel_path = str(file_info.get("path") or "")
                file_path = str(file_info.get("full_path") or os.path.join(repository_path, rel_path))

                if not file_path or not os.path.exists(file_path):
                    parsed_files.append(_minimal_error_record(file_info, "File not found"))
                    continue

                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()

                result = parse_with_best_effort(content, file_info, lang)
                # 표준화: file_path는 상대 경로 유지
                result["file_path"] = file_info.get("path", result.get("file_path", ""))
                # full_code 포함 (크기 제한 내)
                if len(content) <= FULL_CODE_LIMIT:
                    result["full_code"] = content
                parsed_files.append(result)
            except Exception as e:
                print(f"[FileParser] Failed to parse {file_info.get('path', 'unknown')}: {e}")
                parsed_files.append(_minimal_error_record(file_info, str(e)))

        state["parsed_files"] = parsed_files
        state["status"] = "summarizing_files"
        print(f"[FileParser] Successfully parsed {len(parsed_files)} files")
        return state
    except Exception as e:
        state["error"] = f"File parser failed: {str(e)}"
        state["status"] = "error"
        return state


def _resolve_language(file_info: Dict[str, Any]) -> str:
    lang = (file_info.get("language") or "").lower()
    if lang:
        return lang
    path = file_info.get("path", "")
    ext = os.path.splitext(path)[1].lower()
    return {
        ".py": "python",
        ".js": "javascript",
        ".mjs": "javascript",
        ".ts": "typescript",
        ".java": "java",
        ".cpp": "cpp",
        ".cc": "cpp",
        ".cxx": "cpp",
        ".c": "c",
        ".go": "go",
    }.get(ext, "unknown")


def _minimal_error_record(file_info: Dict[str, Any], message: str) -> Dict[str, Any]:
    return {
        "file_path": file_info.get("path", ""),
        "language": file_info.get("language", ""),
        "size": file_info.get("size", 0),
        "parsing_error": message,
        "functions": [],
        "classes": [],
        "imports": [],
        "comments": [],
        "complexity_score": 0,
        "loc": 0,
    }