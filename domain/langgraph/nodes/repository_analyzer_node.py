"""
Repository 전체 분석 노드

GitHub 저장소를 zip으로 다운로드하고 압축을 해제하는 기능을 제공합니다.
전체 저장소 문서 생성의 첫 번째 단계입니다.
"""
import os
import zipfile
import tempfile
import shutil
from typing import Dict, List, Optional
import httpx
from pathlib import Path

from ..document_state import DocumentState
BIG_FILE_SIZE = 5 * 1024 * 1024  # 5MB 이상 제외


def repository_analyzer_node(
    state: DocumentState,
    use_mock: bool = False
) -> DocumentState:
    """
    저장소 분석 노드
    
    역할:
        1. GitHub 저장소를 zip 형식으로 다운로드
        2. 임시 디렉터리에 압축 해제
        3. 코드 파일 목록 추출 및 필터링
    
    입력:
        - repository_name: 저장소 full_name (owner/repo)
        - access_token: GitHub API 토큰 (선택적)
        - use_mock: Mock 모드 사용 여부
    
    출력:
        - repository_path: 압축 해제된 저장소 경로
        - code_files: 분석할 코드 파일 목록
        - repository_structure: 디렉터리 구조 정보
        - status: "analyzing_files"
    """
    try:
        repository_name = state.get("repository_name")
        if not repository_name:
            state["error"] = "Repository name is required"
            state["status"] = "error"
            return state
        
        print(f"[RepositoryAnalyzer] Analyzing repository: {repository_name}")
        
        if use_mock:
            # Mock 모드: 가상의 파일 구조 생성
            mock_files = [
                {"path": "main.py", "type": "file", "language": "python"},
                {"path": "src/app.py", "type": "file", "language": "python"},
                {"path": "src/models/user.py", "type": "file", "language": "python"},
                {"path": "src/utils/helper.py", "type": "file", "language": "python"},
                {"path": "tests/test_app.py", "type": "file", "language": "python"},
                {"path": "README.md", "type": "file", "language": "markdown"},
                {"path": "requirements.txt", "type": "file", "language": "text"}
            ]
            
            state["repository_path"] = "/mock/repository/path"
            state["code_files"] = mock_files
            state["repository_structure"] = {
                "total_files": len(mock_files),
                "code_files": 5,
                "test_files": 1,
                "doc_files": 1,
                "directories": ["src", "src/models", "src/utils", "tests"]
            }
            state["status"] = "analyzing_files"
            return state
        
        # 실제 GitHub API를 통한 저장소 다운로드
        repo_path = _download_repository_zip_sync(repository_name, state.get("access_token"))
        
        if not repo_path:
            state["error"] = f"Failed to download repository: {repository_name}"
            state["status"] = "error"
            return state
        
        # 코드 파일 추출 및 분석
        code_files, repo_structure = _analyze_repository_structure_sync(repo_path)
        
        state["repository_path"] = str(repo_path)
        state["code_files"] = code_files
        state["repository_structure"] = repo_structure
        state["status"] = "analyzing_files"
        
        print(f"[RepositoryAnalyzer] Found {len(code_files)} code files")
        return state
        
    except Exception as e:
        state["error"] = f"Repository analyzer failed: {str(e)}"
        state["status"] = "error"
        return state


def _download_repository_zip_sync(repository_name: str, access_token: Optional[str] = None) -> Optional[Path]:
    """GitHub 저장소를 zip으로 다운로드하고 압축 해제.

    개선 사항:
      1) 기본 브랜치 자동 조회 (API) 후 main/master 순차 시도
      2) codeload.github.com 직접 사용으로 302 리다이렉트 회피
      3) 302 응답 처리 및 로그인/권한 문제 진단 출력
      4) private 저장소 접근 실패 시 명확한 메시지
    """
    try:
        headers = {"User-Agent": "Repository-Analyzer/1.1", "Accept": "application/vnd.github+json"}
        if access_token:
            headers["Authorization"] = f"token {access_token}"

        # 1. 기본 브랜치 조회
        default_branch = "main"
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            try:
                repo_resp = client.get(f"https://api.github.com/repos/{repository_name}", headers=headers)
                if repo_resp.status_code == 200:
                    default_branch = repo_resp.json().get("default_branch", "main")
                else:
                    print(f"[Download] Could not fetch repo metadata (HTTP {repo_resp.status_code}), fallback to 'main'.")
            except Exception as e:
                print(f"[Download] Repo metadata request failed: {e}")

        # 2. 시도할 브랜치 리스트 구성
        branches_to_try = []
        for b in [default_branch, "main", "master"]:
            if b not in branches_to_try:
                branches_to_try.append(b)

        temp_dir = Path(tempfile.mkdtemp(prefix="repo_analysis_"))
        extract_path = temp_dir / "extracted"
        extract_path.mkdir()
        zip_path = temp_dir / "repository.zip"

        # 3. 브랜치별 다운로드 시도 (codeload 사용)
        for branch in branches_to_try:
            zip_url = f"https://codeload.github.com/{repository_name}/zip/refs/heads/{branch}"
            print(f"[Download] Attempting download: {zip_url}")
            try:
                with httpx.Client(timeout=60.0, follow_redirects=True) as client:
                    resp = client.get(zip_url, headers=headers)

                if resp.status_code == 200:
                    # 저장
                    with open(zip_path, "wb") as f:
                        f.write(resp.content)

                    # 압축 해제
                    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                        zip_ref.extractall(extract_path)

                    extracted_dirs = list(extract_path.iterdir())
                    if extracted_dirs:
                        actual_repo_path = extracted_dirs[0]
                        print(f"[Download] Success on branch '{branch}' → {actual_repo_path}")
                        return actual_repo_path
                    else:
                        print("[Download] Zip extracted but no top-level directory found.")
                        return None

                elif resp.status_code == 404:
                    print(f"[Download] Branch '{branch}' not found (404). Trying next...")
                    continue
                elif resp.status_code in (301, 302, 303, 307, 308):
                    print(f"[Download] Redirect encountered (HTTP {resp.status_code}). Using follow_redirects but still failed. Possibly private repo or permission issue.")
                    continue
                elif resp.status_code == 403:
                    print("[Download] 403 Forbidden: Token 권한 부족 또는 private 저장소 접근 불가.")
                    break
                else:
                    print(f"[Download] Unexpected status {resp.status_code} for branch '{branch}'.")
                    continue
            except Exception as e:
                print(f"[Download] Error on branch '{branch}': {e}")
                continue

        print(f"[Download] All attempts failed for {repository_name} (branches: {branches_to_try}).")
        return None
    except Exception as e:
        print(f"[Download] Fatal error downloading repository: {e}")
        return None


def _analyze_repository_structure_sync(repo_path: Path) -> tuple[List[Dict], Dict]:
    """
    저장소 구조 분석 및 코드 파일 추출
    
    Args:
        repo_path: 저장소 경로
    
    Returns:
        (코드 파일 목록, 구조 정보)
    """
    try:
        # 지원하는 코드 파일 확장자
        code_extensions = {
            '.py': 'python',
            '.js': 'javascript', 
            '.ts': 'typescript',
            '.jsx': 'javascript',
            '.tsx': 'typescript',
            '.java': 'java',
            '.cpp': 'cpp',
            '.c': 'c',
            '.h': 'c',
            '.hpp': 'cpp',
            '.go': 'go',
            '.rs': 'rust',
            '.php': 'php',
            '.rb': 'ruby',
            '.cs': 'csharp',
            '.kt': 'kotlin',
            '.swift': 'swift',
            '.scala': 'scala',
            '.sh': 'shell',
            '.sql': 'sql',
            '.html': 'html',
            '.css': 'css',
            '.scss': 'scss',
            '.yaml': 'yaml',
            '.yml': 'yaml',
            '.json': 'json',
            '.xml': 'xml',
            '.md': 'markdown',
            '.rst': 'rst'
        }
        
        # 무시할 디렉터리/파일 패턴
        ignore_patterns = {
            '__pycache__', '.git', '.svn', 'node_modules', '.vscode', '.idea',
            'venv', 'env', '.env', 'build', 'dist', 'target', '.pytest_cache',
            '.coverage', '*.pyc', '*.pyo', '*.pyd', '.DS_Store', 'Thumbs.db'
        }
        
        code_files = []
        directories = set()
        total_files = 0
        code_file_count = 0
        test_file_count = 0
        doc_file_count = 0
        
        # 재귀적으로 파일 탐색
        for file_path in repo_path.rglob('*'):
            if file_path.is_file():
                total_files += 1
                
                # 상대 경로 계산
                relative_path = file_path.relative_to(repo_path)
                path_str = str(relative_path).replace('\\', '/')
                
                # 무시할 파일/디렉터리 체크
                if any(pattern in path_str for pattern in ignore_patterns):
                    continue
                
                # 파일 확장자 확인
                file_ext = file_path.suffix.lower()
                if file_ext in code_extensions:
                    language = code_extensions[file_ext]
                    
                    # 파일 크기 체크 (너무 큰 파일은 제외)
                    try:
                        file_size = file_path.stat().st_size
                        if file_size > BIG_FILE_SIZE:  # 5MB 이상 제외
                            continue
                    except:
                        continue
                    
                    code_files.append({
                        "path": path_str,
                        "full_path": str(file_path),
                        "type": "file",
                        "language": language,
                        "size": file_size,
                        "is_test": _is_test_file(path_str),
                        "is_config": _is_config_file(path_str)
                    })
                    
                    code_file_count += 1
                    
                    # 테스트/문서 파일 구분
                    if _is_test_file(path_str):
                        test_file_count += 1
                    elif language in ['markdown', 'rst']:
                        doc_file_count += 1
                
                # 디렉터리 정보 수집
                parent_dir = relative_path.parent
                if parent_dir != Path('.'):
                    directories.add(str(parent_dir).replace('\\', '/'))
        
        repository_structure = {
            "total_files": total_files,
            "code_files": code_file_count,
            "test_files": test_file_count,
            "doc_files": doc_file_count,
            "directories": sorted(list(directories)),
            "languages": list(set(f["language"] for f in code_files))
        }
        
        # 파일을 중요도 순으로 정렬 (메인 파일, 설정 파일 우선)
        code_files.sort(key=lambda x: _get_file_priority(x["path"]))
        
        return code_files, repository_structure
        
    except Exception as e:
        print(f"[Structure Analysis] Error: {e}")
        return [], {}


def _is_test_file(file_path: str) -> bool:
    """테스트 파일인지 판단"""
    test_patterns = ['test_', '_test.', '/test/', '/tests/', '.test.', '.spec.']
    return any(pattern in file_path.lower() for pattern in test_patterns)


def _is_config_file(file_path: str) -> bool:
    """설정 파일인지 판단"""
    config_patterns = [
        'config', 'setting', 'requirements.txt', 'package.json', 'Dockerfile',
        'docker-compose', '.env', 'makefile', 'cmake', '.yml', '.yaml'
    ]
    file_name = file_path.lower()
    return any(pattern in file_name for pattern in config_patterns)


def _get_file_priority(file_path: str) -> int:
    """파일 우선순위 결정 (낮을수록 우선)"""
    file_name = file_path.lower()
    
    # 최고 우선순위: 메인 엔트리 파일
    if any(name in file_name for name in ['main.py', 'app.py', 'index.', 'server.', '__init__.py']):
        return 1
    
    # 높은 우선순위: 설정 및 핵심 파일
    if _is_config_file(file_path) or 'readme' in file_name:
        return 2
    
    # 중간 우선순위: 일반 소스 파일
    if not _is_test_file(file_path):
        return 3
    
    # 낮은 우선순위: 테스트 파일
    return 4


def cleanup_repository_path(repo_path: str):
    """
    임시로 생성된 저장소 경로 정리
    
    Args:
        repo_path: 정리할 저장소 경로
    """
    try:
        if repo_path and Path(repo_path).exists():
            # 상위 temp 디렉터리 전체 삭제
            temp_parent = Path(repo_path).parent.parent
            if temp_parent.name.startswith("repo_analysis_"):
                shutil.rmtree(temp_parent)
                print(f"[Cleanup] Removed temporary directory: {temp_parent}")
    except Exception as e:
        print(f"[Cleanup] Error removing temp directory: {e}")