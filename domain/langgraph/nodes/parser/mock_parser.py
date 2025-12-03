from typing import Dict, Any
from pathlib import Path


def generate_mock_parsing_result(file_info: Dict[str, Any]) -> Dict[str, Any]:
    file_path = file_info.get("path", "")
    language = file_info.get("language", "")
    file_name = Path(file_path).stem

    functions = []
    classes = []
    imports = []

    if language == "python":
        if "main" in file_name or "app" in file_name:
            functions = [
                {"name": "main", "line_start": 10, "line_end": 25, "docstring": "Main entry"},
                {"name": "setup_app", "line_start": 30, "line_end": 45, "docstring": "Setup"},
            ]
            imports = ["from fastapi import FastAPI", "import uvicorn"]
        elif "test" in file_name:
            functions = [
                {"name": "test_example", "line_start": 8, "line_end": 15, "docstring": "Test"}
            ]
        else:
            functions = [
                {"name": f"process_{file_name}", "line_start": 5, "line_end": 20, "docstring": "Process"}
            ]

    elif language in ("javascript", "typescript"):
        functions = [
            {"name": f"{file_name}Handler", "line_start": 5, "line_end": 20, "docstring": "Handler"}
        ]

    return {
        "file_path": file_path,
        "language": language,
        "size": file_info.get("size", 0),
        "functions": functions,
        "classes": classes,
        "imports": imports,
        "comments": [f"Mock {language} file {file_name}"],
        "complexity_score": len(functions) + 2 * len(classes),
        "loc": file_info.get("size", 0) // 20,
    }
