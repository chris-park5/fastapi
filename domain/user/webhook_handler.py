import httpx
import hmac
import hashlib
from fastapi import Request, HTTPException
from typing import Dict, List, Optional
from app.logging_config import get_logger, log_webhook_event, log_github_api_call, log_document_generation, log_error
from app.config import GITHUB_WEBHOOK_SECRET
from .schemas import WebhookEventResponse

logger = get_logger("webhook_handler")


# 사용자 인증 관련 함수들
async def get_current_user(user_id: int):
    """사용자 ID로 사용자 정보 가져오기"""
    from database import get_db
    from models import User
    from sqlalchemy.orm import Session

    db_gen = get_db()
    db: Session = next(db_gen)

    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        return user
    finally:
        db.close()


async def get_user_access_token(user) -> str:
    """사용자의 액세스 토큰 가져오기"""
    if user.access_token is None or not str(user.access_token).strip():
        raise HTTPException(status_code=401, detail="User access token not found. Please login again.")
    return str(user.access_token)


class WebhookHandler:
    """GitHub 웹훅 처리 클래스"""

    def __init__(self):
        self.webhook_secret = GITHUB_WEBHOOK_SECRET or "default_secret"

    def verify_webhook_signature(self, payload: bytes, signature: Optional[str]) -> bool:
        """웹훅 시그니처 검증"""
        if signature is None:
            return False

        try:
            sha_name, signature = signature.split('=')
            if sha_name != 'sha256':
                return False

            mac = hmac.new(self.webhook_secret.encode(), msg=payload, digestmod=hashlib.sha256)
            return hmac.compare_digest(mac.hexdigest(), signature)
        except Exception as e:
            logger.error(f"Signature verification failed: {e}")
            return False

    async def handle_webhook(
            self,
            request: Request,
            x_github_event: str,
            x_hub_signature_256: Optional[str] = None,
            x_github_delivery: Optional[str] = None
    ) -> WebhookEventResponse:
        """GitHub 웹훅 수신 처리"""
        try:
            # 시그니처 검증
            payload = await request.body()
            if not self.verify_webhook_signature(payload, x_hub_signature_256):
                logger.warning("Invalid webhook signature", extra={
                    "event_type": x_github_event,
                    "delivery_id": x_github_delivery
                })
                raise HTTPException(status_code=403, detail="Invalid signature")

            data = await request.json()
            repository_name = data.get("repository", {}).get("full_name", "unknown")

            log_webhook_event(x_github_event, repository_name, delivery_id=x_github_delivery)

            # 이벤트별 처리
            if x_github_event == "push":
                result = await handle_push_event(data)
                return WebhookEventResponse(
                    success=True,
                    message=result["message"],
                    event_type="push",
                    repository=repository_name,
                    processed=True
                )
            elif x_github_event == "pull_request":
                result = await handle_pull_request_event(data)
                return WebhookEventResponse(
                    success=True,
                    message=result["message"],
                    event_type="pull_request",
                    repository=repository_name,
                    processed=True
                )
            else:
                logger.info(f"Unsupported event type: {x_github_event}", extra={
                    "event_type": x_github_event,
                    "repository": repository_name
                })
                return WebhookEventResponse(
                    success=True,
                    message=f"Event {x_github_event} received but not processed",
                    event_type=x_github_event,
                    repository=repository_name,
                    processed=False
                )

        except HTTPException:
            raise
        except Exception as e:
            log_error("Webhook processing failed", e,
                      event_type=x_github_event, delivery_id=x_github_delivery)
            return WebhookEventResponse(
                success=False,
                message="Webhook processing failed",
                event_type=x_github_event,
                error=str(e)
            )


async def handle_push_event(data: dict):
    """Push 이벤트 처리 - main 브랜치 코드 변화만 추출"""

    ref = data.get("ref")
    repository = data.get("repository", {})
    default_branch = repository.get("default_branch", "main")
    repo_name = repository.get("full_name", "unknown")

    log_webhook_event("push", repo_name, ref=ref, default_branch=default_branch)

    # main 브랜치가 아니면 무시
    if ref != f"refs/heads/{default_branch}":
        logger.info(f"Ignoring non-{default_branch} branch", extra={
            "repository": repo_name,
            "ref": ref,
            "expected_ref": f"refs/heads/{default_branch}"
        })
        return {"message": f"Not {default_branch} branch, ignored"}

    commits = data.get("commits", [])
    full_name = repository.get("full_name")

    # 저장소에 연결된 액세스 토큰 가져오기
    access_token = await _get_repository_access_token(full_name)

    repo_info = {
        "full_name": full_name,
        "default_branch": default_branch,
        "access_token": access_token
    }

    # 핵심 코드 변화만 추출
    code_changes = []
    for commit in commits:
        change_summary = await extract_code_changes(commit, repo_info)
        if change_summary:  # 의미있는 변화가 있을 때만 저장
            code_changes.append(change_summary)

    # 변화가 있는 경우만 저장
    if code_changes:
        total_changes = sum(c["total_changes"] for c in code_changes)
        logger.info("Processing code changes", extra={
            "repository": repo_name,
            "commits": len(code_changes),
            "total_changes": total_changes
        })

        changes_data = {
            "repository": repo_info["full_name"],
            "total_changes": total_changes,
            "code_files": [f for c in code_changes for f in c["code_files"]],
            "commits": code_changes
        }
        await save_code_changes(changes_data, "push")
    else:
        logger.info("No code changes detected", extra={"repository": repo_name})

    return {
        "message": f"Extracted code changes from {len(code_changes)} commits",
        "repository": repo_info["full_name"],
        "changes": code_changes
    }


async def extract_code_changes(commit: dict, repo_info: dict):
    """커밋에서 핵심 코드 변화만 추출"""

    commit_sha = commit.get("id")
    commit_message = commit.get("message", "")

    # GitHub API로 파일 변경 정보 가져오기 (액세스 토큰 사용)
    url = f"https://api.github.com/repos/{repo_info['full_name']}/commits/{commit_sha}"

    headers = {"Accept": "application/vnd.github.v3+json"}
    access_token = repo_info.get("access_token")
    if access_token:
        headers["Authorization"] = f"token {access_token}"

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)

        log_github_api_call(url, response.status_code,
                            commit_sha=commit_sha[:8] if commit_sha else "unknown")

        if response.status_code != 200:
            logger.warning("Failed to fetch commit details", extra={
                "url": url,
                "status_code": response.status_code,
                "commit_sha": commit_sha,
                "has_token": bool(access_token),
                "response_text": response.text[:200] if response.status_code != 404 else "Not found"
            })
            return None

        commit_data = response.json()
        files = commit_data.get("files", [])

        # 코드 파일만 필터링 (문서, 설정 파일 제외)
        code_files = []
        code_extensions = {'.py', '.js', '.ts', '.java', '.cpp', '.c', '.go', '.rs', '.php', '.rb', '.cs', '.kt',
                           '.swift'}

        for file_info in files:
            filename = file_info.get("filename", "")
            file_ext = '.' + filename.split('.')[-1] if '.' in filename else ''

            # 코드 파일이고 의미있는 변화가 있는 경우만
            if file_ext in code_extensions and file_info.get("changes", 0) > 0:
                patch_content = file_info.get("patch")
                code_files.append({
                    "filename": filename,
                    "status": file_info.get("status"),  # added, modified, removed
                    "changes": file_info.get("changes", 0),
                    "additions": file_info.get("additions", 0),
                    "deletions": file_info.get("deletions", 0),
                    "patch": patch_content  # 실제 diff 내용 추가!
                })

                # 디버깅: patch 내용 확인
                if patch_content:
                    logger.info(f"Found patch for {filename}: {len(patch_content)} characters")
                else:
                    logger.warning(f"No patch content for {filename} despite {file_info.get('changes', 0)} changes")

        # 코드 변화가 없으면 None 반환
        if not code_files:
            return None

        # 핵심 정보만 반환
        return {
            "sha": commit_sha[:8] if commit_sha else "",  # 짧은 SHA
            "message": commit_message,
            "timestamp": commit.get("timestamp"),
            "code_files": code_files,
            "total_changes": sum(f["changes"] for f in code_files)
        }
    ##############################################################################################################


async def handle_pull_request_event(data: dict):
    """PR merge 이벤트 처리 - main 브랜치 코드 변화만 추출"""

    action = data.get("action")
    pull_request = data.get("pull_request", {})
    repository = data.get("repository", {})

    # merge된 PR만 처리
    if action != "closed" or not pull_request.get("merged", False):
        return {"message": f"PR not merged, ignored"}

    # main 브랜치로의 merge만 처리
    base_branch = pull_request.get("base", {}).get("ref")
    default_branch = repository.get("default_branch", "main")

    if base_branch != default_branch:
        return {"message": f"Not merged to {default_branch}, ignored"}

    # 핵심 PR 정보만
    pr_summary = {
        "number": pull_request.get("number"),
        "title": pull_request.get("title"),
        "author": pull_request.get("user", {}).get("login"),
        "merged_by": pull_request.get("merged_by", {}).get("login"),
        "merged_at": pull_request.get("merged_at")
    }

    full_name = repository.get("full_name")
    access_token = await _get_repository_access_token(full_name)

    repo_info = {
        "full_name": full_name,
        "default_branch": default_branch,
        "access_token": access_token
    }

    # PR의 코드 변화만 추출
    code_changes = await extract_pr_code_changes(repo_info, pr_summary)

    # 코드 변화가 있는 경우만 저장
    total_changes = code_changes.get("total_changes", 0)
    if isinstance(total_changes, int) and total_changes > 0:
        changes_data = {
            "repository": repo_info["full_name"],
            "pr_number": pr_summary["number"],
            "pr_title": pr_summary["title"],
            "merged_by": pr_summary["merged_by"],
            "timestamp": pr_summary["merged_at"],
            **code_changes
        }
        await save_code_changes(changes_data, "pr_merge")

    return {
        "message": f"Extracted code changes from merged PR #{pr_summary['number']}",
        "repository": repo_info["full_name"],
        "pr_summary": pr_summary,
        "code_changes": code_changes
    }


async def extract_pr_code_changes(repo_info: dict, pr_summary: dict):
    """PR에서 코드 변화만 추출"""

    pr_number = pr_summary["number"]

    async with httpx.AsyncClient() as client:
        # PR의 파일 변경 정보 가져오기
        response = await client.get(
            f"https://api.github.com/repos/{repo_info['full_name']}/pulls/{pr_number}/files",
            headers={"Accept": "application/vnd.github.v3+json"}
        )

        if response.status_code != 200:
            return {"error": f"Failed to fetch PR files: {response.status_code}"}

        files = response.json()

        # 코드 파일만 필터링
        code_extensions = {'.py', '.js', '.ts', '.java', '.cpp', '.c', '.go', '.rs', '.php', '.rb', '.cs', '.kt',
                           '.swift'}
        code_changes = []

        for file_info in files:
            filename = file_info.get("filename", "")
            file_ext = '.' + filename.split('.')[-1] if '.' in filename else ''

            # 코드 파일이고 의미있는 변화가 있는 경우만
            if file_ext in code_extensions and file_info.get("changes", 0) > 0:
                code_changes.append({
                    "filename": filename,
                    "status": file_info.get("status"),
                    "changes": file_info.get("changes", 0),
                    "additions": file_info.get("additions", 0),
                    "deletions": file_info.get("deletions", 0)
                })

        return {
            "total_code_files": len(code_changes),
            "total_changes": sum(f["changes"] for f in code_changes),
            "files": code_changes
        }


async def save_code_changes(changes: dict, source: str):
    """코드 변화를 데이터베이스에 저장 (핵심 정보만)"""
    # 실제 구현: SQLAlchemy 세션으로 CodeChange 및 FileChange에 저장
    from database import SessionLocal
    from models import Repository, CodeChange, FileChange
    from datetime import datetime

    def _parse_timestamp(ts):
        if not ts:
            return None
        if isinstance(ts, datetime):
            return ts
        try:
            # GitHub timestamp 예: '2025-10-11T12:34:56Z'
            if isinstance(ts, str) and ts.endswith('Z'):
                ts = ts.replace('Z', '+00:00')
            return datetime.fromisoformat(ts)
        except Exception:
            return None

    session = SessionLocal()
    saved_entries = []
    try:
        repo_full = changes.get('repository')
        repo = None
        if repo_full:
            repo = session.query(Repository).filter(Repository.full_name == repo_full).first()

        # push 이벤트에서는 여러 커밋이 넘어옴
        if source == 'push' and isinstance(changes.get('commits'), list):
            for commit in changes.get('commits', []):
                sha = commit.get('sha') or commit.get('id') or ''
                message = commit.get('message')
                ts = _parse_timestamp(commit.get('timestamp') or commit.get('committed_date'))
                total = commit.get('total_changes', commit.get('total_changes', 0))

                code_change = CodeChange(
                    commit_sha=sha,
                    commit_message=message,
                    author_name=(commit.get('author') or {}).get('name') if isinstance(commit.get('author'),
                                                                                       dict) else commit.get('author'),
                    author_email=(commit.get('author') or {}).get('email') if isinstance(commit.get('author'),
                                                                                         dict) else None,
                    repository_id=repo.id if repo else None,
                    source=source,
                    total_changes=total or 0,
                    timestamp=ts
                )
                session.add(code_change)
                session.commit()
                session.refresh(code_change)

                for f in commit.get('code_files', []):
                    fc = FileChange(
                        filename=f.get('filename'),
                        status=f.get('status'),
                        changes=f.get('changes', 0),
                        additions=f.get('additions', 0),
                        deletions=f.get('deletions', 0),
                        patch=f.get('patch'),
                        code_change_id=code_change.id
                    )
                    session.add(fc)
                session.commit()

                saved_entries.append({'id': code_change.id, 'sha': sha})

        else:
            # PR 병합 등 단일 변경 블록 처리: files 또는 code_files 또는 files key 사용
            sha = str(changes.get('pr_number') or changes.get('sha') or '')
            message = changes.get('pr_title') or changes.get('message')
            ts = _parse_timestamp(changes.get('timestamp') or changes.get('merged_at'))
            total = changes.get('total_changes', 0)

            code_change = CodeChange(
                commit_sha=sha,
                commit_message=message,
                author_name=changes.get('merged_by') or changes.get('author'),
                author_email=None,
                repository_id=repo.id if repo else None,
                source=source,
                total_changes=total or 0,
                timestamp=ts
            )
            session.add(code_change)
            session.commit()
            session.refresh(code_change)

            files = changes.get('files') or changes.get('code_files') or []
            for f in files:
                fc = FileChange(
                    filename=f.get('filename'),
                    status=f.get('status'),
                    changes=f.get('changes', 0),
                    additions=f.get('additions', 0),
                    deletions=f.get('deletions', 0),
                    patch=f.get('patch'),
                    code_change_id=code_change.id
                )
                session.add(fc)
            session.commit()

            saved_entries.append({'id': code_change.id, 'sha': sha})

        # 문서 자동 생성 호출
        logger.info(f"Triggering document generation for {len(saved_entries)} code changes")
        for entry in saved_entries:
            try:
                await _trigger_document_generation(entry['id'])
            except Exception as e:
                log_error(f"Document generation failed for CodeChange {entry['id']}", e,
                          code_change_id=entry['id'])
                # 문서 생성 실패해도 웹훅 처리는 성공으로 처리

        return {"saved": saved_entries}

    except Exception as e:
        session.rollback()
        log_error("Error saving code changes", e, source=source)
        raise HTTPException(status_code=500, detail=f"Failed to save code changes: {str(e)}")
    finally:
        session.close()


async def _trigger_document_generation(code_change_id: int):
    """문서 생성을 비동기로 트리거"""
    try:
        from domain.langgraph.document_service import get_document_service
        from app.config import LANGGRAPH_USE_MOCK
        # 환경변수 LANGGRAPH_USE_MOCK 으로 mock 모드 전환 가능
        document_service = get_document_service(use_mock=LANGGRAPH_USE_MOCK)

        log_document_generation(code_change_id, "starting")
        result = await document_service.process_code_change(code_change_id)

        if result["success"]:
            log_document_generation(code_change_id, "success",
                                    title=result.get('title', 'Unknown'),
                                    action=result.get('action', 'unknown'))
        else:
            # ▼▼▼ 이 두 줄을 추가해 주세요! ▼▼▼
            error_msg = result.get('error', 'Unknown error')
            print(f"\n[DEBUG] 문서 생성 실패 원인: {error_msg}\n")

            log_document_generation(code_change_id, "failed", error=error_msg)

    except Exception as e:
        log_error(f"Error triggering document generation for CodeChange {code_change_id}", e,
                  code_change_id=code_change_id)
        # 예외를 다시 발생시키지 않음 - 문서 생성 실패가 웹훅 처리를 방해하면 안됨


async def save_webhook_info(webhook_data: dict):
    """Webhook 정보를 데이터베이스에 저장하고 Repository도 자동 등록"""
    from database import get_db
    from models import WebhookRegistration, Repository, User
    from sqlalchemy.orm import Session

    # 데이터베이스 세션 가져오기
    db_gen = get_db()
    db: Session = next(db_gen)

    try:
        repo_owner = webhook_data.get("repo_owner")
        repo_name = webhook_data.get("repo_name")
        full_name = f"{repo_owner}/{repo_name}"
        access_token = webhook_data.get("access_token")

        # 1. 액세스 토큰으로 User 찾기
        user = db.query(User).filter(User.access_token == access_token).first()
        if not user:
            logger.warning(f"User not found for access_token when saving webhook for {full_name}")

        # 2. Repository 찾기 또는 생성
        repository = db.query(Repository).filter(Repository.full_name == full_name).first()

        if not repository:
            # GitHub API로 저장소 상세 정보 가져오기 (토큰이 있는 경우만)
            if access_token:
                repo_details = await _fetch_repository_details(full_name, access_token)
            else:
                repo_details = {"id": 0, "default_branch": "main", "private": False}

            repository = Repository(
                github_id=repo_details.get("id", 0),
                name=repo_name,
                full_name=full_name,
                default_branch=repo_details.get("default_branch", "main"),
                is_private=repo_details.get("private", False),
                owner_id=user.id if user else None
            )
            db.add(repository)
            db.commit()
            db.refresh(repository)
            logger.info(f"Repository {full_name} created and linked to user {user.username if user else 'unknown'}")

        # 3. WebhookRegistration 객체 생성
        webhook_registration = WebhookRegistration(
            repo_owner=repo_owner,
            repo_name=repo_name,
            webhook_id=webhook_data.get("webhook_id"),
            webhook_url=webhook_data.get("webhook_url"),
            access_token=access_token,  # 실제로는 암호화 필요
            is_active=True,
            repository_id=repository.id  # Repository 연결
        )

        # 데이터베이스에 저장
        db.add(webhook_registration)
        db.commit()
        db.refresh(webhook_registration)

        logger.info("Webhook info saved successfully", extra={
            "webhook_id": webhook_data.get('webhook_id'),
            "repo": f"{webhook_data.get('repo_owner')}/{webhook_data.get('repo_name')}"
        })
        return {"message": "Webhook info saved successfully", "id": webhook_registration.id}

    except Exception as e:
        db.rollback()
        log_error("Failed to save webhook info", e, webhook_id=webhook_data.get('webhook_id'))
        raise HTTPException(status_code=500, detail=f"Failed to save webhook info: {str(e)}")
    finally:
        db.close()


async def _get_repository_access_token(full_name: str) -> str:
    """저장소의 액세스 토큰 가져오기"""
    from database import get_db
    from models import WebhookRegistration
    from sqlalchemy.orm import Session

    db_gen = get_db()
    db: Session = next(db_gen)

    try:
        # 저장소의 웹훅 등록 정보에서 토큰 가져오기
        repo_owner, repo_name = full_name.split("/") if "/" in full_name else (full_name, "")
        webhook_reg = db.query(WebhookRegistration).filter(
            WebhookRegistration.repo_owner == repo_owner,
            WebhookRegistration.repo_name == repo_name,
            WebhookRegistration.is_active == True
        ).first()

        if webhook_reg is not None and webhook_reg.access_token is not None:
            return str(webhook_reg.access_token)
        else:
            logger.warning(f"No access token found for repository {full_name}")
            return ""

    except Exception as e:
        logger.error(f"Failed to get access token for {full_name}: {e}")
        return ""
    finally:
        db.close()


async def _fetch_repository_details(full_name: str, access_token: str) -> dict:
    """GitHub API로 저장소 상세 정보 가져오기"""
    import httpx

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"https://api.github.com/repos/{full_name}",
            headers={
                "Authorization": f"token {access_token}",
                "Accept": "application/vnd.github.v3+json"
            }
        )

        if response.status_code == 200:
            return response.json()
        else:
            logger.warning(f"Failed to fetch repository details for {full_name}: {response.status_code}")
            return {"id": 0, "default_branch": "main", "private": False}


async def delete_webhook_info(webhook_id: int):
    """데이터베이스에서 Webhook 정보 삭제"""
    from database import get_db
    from models import WebhookRegistration
    from sqlalchemy.orm import Session

    # 데이터베이스 세션 가져오기
    db_gen = get_db()
    db: Session = next(db_gen)

    try:
        # webhook_id로 해당 레코드 찾기
        webhook_registration = db.query(WebhookRegistration).filter(
            WebhookRegistration.webhook_id == webhook_id
        ).first()

        if webhook_registration:
            # 레코드 삭제
            db.delete(webhook_registration)
            db.commit()
            logger.info("Webhook info deleted successfully", extra={"webhook_id": webhook_id})
            return {"message": "Webhook info deleted successfully"}
        else:
            logger.warning("Webhook not found in database", extra={"webhook_id": webhook_id})
            return {"message": "Webhook not found in database"}

    except Exception as e:
        db.rollback()
        log_error("Failed to delete webhook info", e, webhook_id=webhook_id)
        raise HTTPException(status_code=500, detail=f"Failed to delete webhook info: {str(e)}")
    finally:
        db.close()