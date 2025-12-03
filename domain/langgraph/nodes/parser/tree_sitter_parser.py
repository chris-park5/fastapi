from typing import Dict, Any, List, Optional
import importlib.util
from .fallback_parser import (
    parse_python_fallback,
    parse_javascript_fallback,
    parse_java_fallback,
    parse_generic,
)


def _try_tree_sitter_parse(content: str, file_info: Dict[str, Any], language_name: str) -> Optional[Dict[str, Any]]:
    try:
        from tree_sitter import Parser, Language
        # 각 언어 모듈은 선택적으로 설치되어 있을 수 있음
        lang: Optional[Language] = None
        if language_name == "python":
            if importlib.util.find_spec("tree_sitter_python") is None:
                return None
            import tree_sitter_python as tsp  # type: ignore
            lang = Language(tsp.language())
        elif language_name == "javascript":
            if importlib.util.find_spec("tree_sitter_javascript") is None:
                return None
            import tree_sitter_javascript as tsjs  # type: ignore
            lang = Language(tsjs.language())
        elif language_name == "typescript":
            if importlib.util.find_spec("tree_sitter_typescript") is None:
                return None
            import tree_sitter_typescript as tsts  # type: ignore
            lang = Language(tsts.language_typescript())
        elif language_name == "java":
            if importlib.util.find_spec("tree_sitter_java") is None:
                return None
            import tree_sitter_java as tsj  # type: ignore
            lang = Language(tsj.language())
        elif language_name in ("cpp", "c"):
            if importlib.util.find_spec("tree_sitter_cpp") is None:
                return None
            import tree_sitter_cpp as tscpp  # type: ignore
            lang = Language(tscpp.language())
        elif language_name == "go":
            if importlib.util.find_spec("tree_sitter_go") is None:
                return None
            import tree_sitter_go as tsgo  # type: ignore
            lang = Language(tsgo.language())
        else:
            return None

        if not lang:
            return None

        parser = Parser()
        parser.language = lang
        tree = parser.parse(bytes(content, "utf8"))
        root = tree.root_node

        functions: List[Dict[str, Any]] = []
        classes: List[Dict[str, Any]] = []
        imports: List[str] = []

        patterns = {
            "python": {
                "functions": ["function_definition"],
                "classes": ["class_definition"],
                "imports": ["import_statement", "import_from_statement"],
            },
            "javascript": {
                "functions": ["function_declaration", "arrow_function", "method_definition"],
                "classes": ["class_declaration"],
                "imports": ["import_statement"],
            },
            "typescript": {
                "functions": ["function_declaration", "arrow_function", "method_definition", "function_signature"],
                "classes": ["class_declaration", "interface_declaration"],
                "imports": ["import_statement"],
            },
            "java": {
                "functions": ["method_declaration", "constructor_declaration"],
                "classes": ["class_declaration", "interface_declaration"],
                "imports": ["import_declaration"],
            },
            "cpp": {
                "functions": ["function_definition", "function_declarator"],
                "classes": ["class_specifier", "struct_specifier"],
                "imports": ["preproc_include"],
            },
            "go": {
                "functions": ["function_declaration", "method_declaration"],
                "classes": ["type_declaration"],
                "imports": ["import_declaration"],
            },
        }.get(language_name, {})

        def id_text(node) -> str:
            for ch in node.children:
                if ch.type == "identifier":
                    return ch.text.decode(errors="ignore")
            return "unknown"

        def walk(node):
            t = node.type
            if t in patterns.get("functions", []):
                functions.append({
                    "name": id_text(node),
                    "line_start": node.start_point[0] + 1,
                    "line_end": node.end_point[0] + 1,
                    "docstring": "",
                })
            elif t in patterns.get("classes", []):
                classes.append({
                    "name": id_text(node),
                    "line_start": node.start_point[0] + 1,
                    "line_end": node.end_point[0] + 1,
                    "methods": [],
                })
            elif t in patterns.get("imports", []):
                imports.append(node.type)
            for c in node.children:
                walk(c)

        walk(root)

        return {
            "file_path": file_info.get("path", ""),
            "language": language_name,
            "size": file_info.get("size", 0),
            "functions": functions,
            "classes": classes,
            "imports": imports,
            "comments": [],
            "complexity_score": len(functions) + 2 * len(classes),
            "loc": len(content.splitlines()),
        }
    except Exception:
        return None


def parse_with_best_effort(content: str, file_info: Dict[str, Any], language_name: str) -> Dict[str, Any]:
    ts = _try_tree_sitter_parse(content, file_info, language_name)
    if ts is not None:
        return ts
    # fallback
    if language_name == "python":
        return parse_python_fallback(content, file_info)
    if language_name in ("javascript", "typescript"):
        return parse_javascript_fallback(content, file_info)
    if language_name == "java":
        return parse_java_fallback(content, file_info)
    return parse_generic(content, file_info)
