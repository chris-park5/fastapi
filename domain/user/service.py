"""
GitHub API 서비스 클래스
"""
import httpx
from typing import Dict, List, Optional
from app.logging_config import get_logger, log_github_api_call, log_error
from app.config import GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET, GITHUB_WEBHOOK_SECRET
from .schemas import (
    SetupWebhookRequest, WebhookResponse, RepositoriesResponse,
    WebhooksListResponse, DeleteWebhookResponse, RepositoryInfo, WebhookInfo
)

logger = get_logger("github_service")


class GitHubService:
    """GitHub API 연동 서비스"""

    def __init__(self):
        self.base_url = "https://api.github.com"

    async def setup_repository_webhook(self, request: SetupWebhookRequest) -> WebhookResponse:
        """저장소에 웹훅 설정"""
        try:
            webhook_config = {
                "name": "web",
                "active": True,
                "events": ["push", "pull_request"],
                "config": {
                    "url": f"{request.webhook_url}/github/webhook",
                    "content_type": "json",
                    "secret": GITHUB_WEBHOOK_SECRET,
                    "insecure_ssl": "0"
                }
            }

            async with httpx.AsyncClient() as client:
                url = f"{self.base_url}/repos/{request.repo_owner}/{request.repo_name}/hooks"
                response = await client.post(
                    url,
                    headers={
                        "Authorization": f"token {request.access_token}",
                        "Accept": "application/vnd.github.v3+json"
                    },
                    json=webhook_config
                )

                log_github_api_call(url, response.status_code,
                                    repo=f"{request.repo_owner}/{request.repo_name}")

                if response.status_code == 201:
                    webhook_data = response.json()

                    # 데이터베이스에 저장
                    await self._save_webhook_info({
                        "repo_owner": request.repo_owner,
                        "repo_name": request.repo_name,
                        "webhook_id": webhook_data["id"],
                        "webhook_url": webhook_data["config"]["url"],
                        "access_token": request.access_token
                    })

                    logger.info("Webhook created successfully", extra={
                        "repository": f"{request.repo_owner}/{request.repo_name}",
                        "webhook_id": webhook_data["id"]
                    })

                    return WebhookResponse(
                        success=True,
                        message="Webhook created successfully",
                        webhook_id=webhook_data["id"],
                        webhook_url=webhook_data["config"]["url"]
                    )
                else:
                    error_msg = f"Failed to create webhook: {response.status_code}"
                    logger.error(error_msg, extra={
                        "repository": f"{request.repo_owner}/{request.repo_name}",
                        "status_code": response.status_code,
                        "response": response.text
                    })

                    return WebhookResponse(
                        success=False,
                        message=error_msg,
                        error=response.text
                    )

        except Exception as e:
            log_error("Webhook setup failed", e,
                      repository=f"{request.repo_owner}/{request.repo_name}")
            return WebhookResponse(
                success=False,
                message="Webhook setup failed",
                error=str(e)
            )

    async def get_user_repositories(self, access_token: str) -> RepositoriesResponse:
        """사용자 저장소 목록 조회"""
        try:
            async with httpx.AsyncClient() as client:
                url = f"{self.base_url}/user/repos"
                response = await client.get(
                    url,
                    headers={
                        "Authorization": f"token {access_token}",
                        "Accept": "application/vnd.github.v3+json"
                    },
                    params={
                        "type": "owner",
                        "sort": "updated",
                        "per_page": 100
                    }
                )

                log_github_api_call(url, response.status_code)

                if response.status_code == 200:
                    repos_data = response.json()
                    repositories = []

                    for repo in repos_data:
                        if repo.get("permissions", {}).get("admin", False):
                            repositories.append(RepositoryInfo(
                                name=repo["name"],
                                full_name=repo["full_name"],
                                private=repo["private"],
                                default_branch=repo["default_branch"],
                                permissions=repo["permissions"]
                            ))

                    logger.info(f"Retrieved {len(repositories)} repositories with admin access")

                    return RepositoriesResponse(
                        success=True,
                        repositories=repositories,
                        total=len(repositories)
                    )
                else:
                    error_msg = "Failed to fetch repositories"
                    log_error(error_msg, status_code=response.status_code)

                    return RepositoriesResponse(
                        success=False,
                        error=f"{error_msg}: {response.status_code}"
                    )

        except Exception as e:
            log_error("Repository fetch failed", e)
            return RepositoriesResponse(
                success=False,
                error=str(e)
            )

    async def list_repository_webhooks(self, repo_owner: str, repo_name: str,
                                       access_token: str) -> WebhooksListResponse:
        """저장소의 웹훅 목록 조회"""
        try:
            async with httpx.AsyncClient() as client:
                url = f"{self.base_url}/repos/{repo_owner}/{repo_name}/hooks"
                response = await client.get(
                    url,
                    headers={
                        "Authorization": f"token {access_token}",
                        "Accept": "application/vnd.github.v3+json"
                    }
                )

                log_github_api_call(url, response.status_code, repo=f"{repo_owner}/{repo_name}")

                if response.status_code == 200:
                    hooks_data = response.json()
                    webhooks = []

                    for hook in hooks_data:
                        webhooks.append(WebhookInfo(
                            id=hook["id"],
                            name=hook["name"],
                            active=hook["active"],
                            events=hook["events"],
                            config=hook["config"]
                        ))

                    return WebhooksListResponse(
                        success=True,
                        webhooks=webhooks,
                        total=len(webhooks)
                    )
                else:
                    return WebhooksListResponse(
                        success=False,
                        error=f"Failed to fetch webhooks: {response.status_code}"
                    )

        except Exception as e:
            log_error("Webhook list fetch failed", e, repository=f"{repo_owner}/{repo_name}")
            return WebhooksListResponse(
                success=False,
                error=str(e)
            )

    async def delete_repository_webhook(self, webhook_id: int, repo_owner: str, repo_name: str,
                                        access_token: str) -> DeleteWebhookResponse:
        """저장소의 웹훅 삭제"""
        try:
            async with httpx.AsyncClient() as client:
                url = f"{self.base_url}/repos/{repo_owner}/{repo_name}/hooks/{webhook_id}"
                response = await client.delete(
                    url,
                    headers={
                        "Authorization": f"token {access_token}",
                        "Accept": "application/vnd.github.v3+json"
                    }
                )

                log_github_api_call(url, response.status_code,
                                    repo=f"{repo_owner}/{repo_name}", webhook_id=webhook_id)

                if response.status_code == 204:
                    # 데이터베이스에서도 삭제
                    await self._delete_webhook_info(webhook_id)

                    logger.info("Webhook deleted successfully", extra={
                        "repository": f"{repo_owner}/{repo_name}",
                        "webhook_id": webhook_id
                    })

                    return DeleteWebhookResponse(
                        success=True,
                        message="Webhook deleted successfully"
                    )
                else:
                    return DeleteWebhookResponse(
                        success=False,
                        message=f"Failed to delete webhook: {response.status_code}",
                        error=response.text
                    )

        except Exception as e:
            log_error("Webhook deletion failed", e,
                      repository=f"{repo_owner}/{repo_name}", webhook_id=webhook_id)
            return DeleteWebhookResponse(
                success=False,
                message="Webhook deletion failed",
                error=str(e)
            )

    async def get_repository_webhook_status(self, repo_owner: str, repo_name: str, access_token: str) -> Dict:
        """저장소의 웹훅 설정 상태 확인"""
        try:
            webhooks_response = await self.list_repository_webhooks(repo_owner, repo_name, access_token)

            if not webhooks_response.success:
                return {"error": webhooks_response.error}

            # CICDAutoDoc 웹훅 찾기
            cicd_webhooks = []
            for webhook in webhooks_response.webhooks:
                if "github/webhook" in webhook.config.get("url", ""):
                    cicd_webhooks.append({
                        "id": webhook.id,
                        "active": webhook.active,
                        "events": webhook.events,
                        "url": webhook.config.get("url")
                    })

            return {
                "repository": f"{repo_owner}/{repo_name}",
                "total_webhooks": len(webhooks_response.webhooks),
                "cicd_webhooks": cicd_webhooks,
                "has_cicd_webhook": len(cicd_webhooks) > 0
            }

        except Exception as e:
            log_error("Webhook status check failed", e, repository=f"{repo_owner}/{repo_name}")
            return {"error": str(e)}

    async def _save_webhook_info(self, webhook_data: Dict):
        """웹훅 정보를 데이터베이스에 저장"""
        try:
            # webhook_handler의 기존 함수 재사용
            from .webhook_handler import save_webhook_info
            await save_webhook_info(webhook_data)
        except Exception as e:
            log_error("Failed to save webhook info", e, webhook_id=webhook_data.get("webhook_id"))

    async def _delete_webhook_info(self, webhook_id: int):
        """데이터베이스에서 웹훅 정보 삭제"""
        try:
            # webhook_handler의 기존 함수 재사용
            from .webhook_handler import delete_webhook_info
            await delete_webhook_info(webhook_id)
        except Exception as e:
            log_error("Failed to delete webhook info", e, webhook_id=webhook_id)