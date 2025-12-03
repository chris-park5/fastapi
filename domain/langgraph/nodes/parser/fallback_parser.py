from typing import Dict, Any
import re
from .utils import extract_comments


def parse_python_fallback(content: str, file_info: Dict[str, Any]) -> Dict[str, Any]:
    function_pattern = re.compile(r'^def\s+(\w+)\s*\([^)]*\):', re.MULTILINE)
    class_pattern = re.compile(r'^class\s+(\w+).*?:', re.MULTILINE)
    import_pattern = re.compile(r'^(import\s+.+|from\s+.+\s+import\s+.+)', re.MULTILINE)

    functions = []
    classes = []
    imports = []
    lines = content.splitlines()

    for m in function_pattern.finditer(content):
        name = m.group(1)
        line = content[:m.start()].count('\n') + 1
        functions.append({"name": name, "line_start": line, "line_end": line + 10, "docstring": ""})

    for m in class_pattern.finditer(content):
        name = m.group(1)
        line = content[:m.start()].count('\n') + 1
        classes.append({"name": name, "line_start": line, "line_end": line + 20, "methods": []})

    for m in import_pattern.finditer(content):
        imports.append(m.group(1).strip())

    return {
        "file_path": file_info.get("path", ""),
        "language": "python",
        "size": file_info.get("size", 0),
        "functions": functions,
        "classes": classes,
        "imports": imports,
        "comments": extract_comments(content),
        "complexity_score": len(functions) + 2 * len(classes),
        "loc": len(lines),
    }


def parse_javascript_fallback(content: str, file_info: Dict[str, Any]) -> Dict[str, Any]:
    function_pattern = re.compile(r'function\s+(\w+)|const\s+(\w+)\s*=.*?=>|(\w+)\s*:\s*function')
    class_pattern = re.compile(r'class\s+(\w+)')
    import_pattern = re.compile(r'import.*?from\s+[\'\"]([^\'\"]+)[\'\"]|import\s+[\'\"]([^\'\"]+)[\'\"]')

    functions = []
    classes = []
    imports = []
    lines = content.splitlines()

    for m in function_pattern.finditer(content):
        name = m.group(1) or m.group(2) or m.group(3)
        if name:
            line = content[:m.start()].count('\n') + 1
            functions.append({"name": name, "line_start": line, "line_end": line + 5, "docstring": ""})

    for m in class_pattern.finditer(content):
        name = m.group(1)
        line = content[:m.start()].count('\n') + 1
        classes.append({"name": name, "line_start": line, "line_end": line + 10, "methods": []})

    for m in import_pattern.finditer(content):
        imp = m.group(1) or m.group(2)
        if imp:
            imports.append(f"import from '{imp}'")

    return {
        "file_path": file_info.get("path", ""),
        "language": file_info.get("language", "javascript"),
        "size": file_info.get("size", 0),
        "functions": functions,
        "classes": classes,
        "imports": imports,
        "comments": extract_comments(content),
        "complexity_score": len(functions) + 2 * len(classes),
        "loc": len(lines),
    }


def parse_java_fallback(content: str, file_info: Dict[str, Any]) -> Dict[str, Any]:
    method_pattern = re.compile(r'(public|private|protected).*?\s+(\w+)\s*\([^)]*\)\s*{')
    class_pattern = re.compile(r'(public\s+)?class\s+(\w+)')
    import_pattern = re.compile(r'import\s+([^;]+);')

    functions = []
    classes = []
    imports = []
    lines = content.splitlines()

    for m in method_pattern.finditer(content):
        name = m.group(2)
        line = content[:m.start()].count('\n') + 1
        functions.append({"name": name, "line_start": line, "line_end": line + 5, "docstring": ""})

    for m in class_pattern.finditer(content):
        name = m.group(2)
        line = content[:m.start()].count('\n') + 1
        classes.append({"name": name, "line_start": line, "line_end": line + 20, "methods": []})

    for m in import_pattern.finditer(content):
        imports.append(m.group(1).strip())

    return {
        "file_path": file_info.get("path", ""),
        "language": "java",
        "size": file_info.get("size", 0),
        "functions": functions,
        "classes": classes,
        "imports": imports,
        "comments": extract_comments(content),
        "complexity_score": len(functions) + 2 * len(classes),
        "loc": len(lines),
    }


def parse_generic(content: str, file_info: Dict[str, Any]) -> Dict[str, Any]:
    lines = content.splitlines()
    return {
        "file_path": file_info.get("path", ""),
        "language": file_info.get("language", "unknown"),
        "size": file_info.get("size", 0),
        "functions": [],
        "classes": [],
        "imports": [],
        "comments": extract_comments(content),
        "complexity_score": 1,
        "loc": len(lines),
    }
