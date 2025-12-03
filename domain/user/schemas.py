"""
GitHub 관련 Pydantic 스키마 정의
"""
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any


class SetupWebhookRequest(BaseModel):
    """웹훅 설정 요청"""
    repo_owner: str = Field(description="저장소 소유자", examples=["octocat"])
    repo_name: str = Field(description="저장소 이름", examples=["Hello-World"])
    access_token: str = Field(description="GitHub 액세스 토큰", examples=["gho_xxxxxxxxxxxx"])
    webhook_url: str = Field(description="웹훅 수신 URL", examples=["https://api.example.com"])


class WebhookInfo(BaseModel):
    """웹훅 정보"""
    id: int = Field(description="웹훅 고유 ID", examples=[12345678])
    name: str = Field(description="웹훅 이름", examples=["web"])
    active: bool = Field(description="웹훅 활성 상태", examples=[True])
    events: List[str] = Field(description="등록된 이벤트 목록", examples=[["push", "pull_request"]])
    config: Dict[str, Any] = Field(description="웹훅 구성 정보", examples=[{"url": "https://api.example.com/webhook", "content_type": "json"}])


class WebhookResponse(BaseModel):
    """웹훅 등록 응답"""
    success: bool = Field(description="요청 성공 여부", examples=[True])
    message: str = Field(description="응답 메시지", examples=["Webhook created successfully."])
    webhook_id: Optional[int] = Field(default=None, description="등록된 웹훅 ID", examples=[12345678])
    webhook_url: Optional[str] = Field(default=None, description="웹훅 URL", examples=["https://api.example.com/webhook"])
    error: Optional[str] = Field(default=None, description="오류 메시지", examples=[None])


class RepositoryInfo(BaseModel):
    """저장소 정보"""
    name: str = Field(description="저장소 이름", examples=["Hello-World"])
    full_name: str = Field(description="전체 저장소 이름 (owner/repo)", examples=["octocat/Hello-World"])
    owner: str = Field(description="저장소 소유자", examples=["octocat"])
    private: bool = Field(description="비공개 저장소 여부", examples=[False])
    default_branch: str = Field(description="기본 브랜치 이름", examples=["main"])
    permissions: Dict[str, Any] = Field(
        description="저장소 권한 정보",
        examples=[{"admin": True, "push": True, "pull": True}]
    )


class RepositoriesResponse(BaseModel):
    """저장소 목록 조회 응답"""
    success: bool = Field(description="요청 성공 여부", examples=[True])
    repositories: List[RepositoryInfo] = Field(
        description="사용자 저장소 목록",
        examples=[
            [
                {
                    "name": "Hello-World",
                    "full_name": "octocat/Hello-World",
                    "owner": "octocat",
                    "private": False,
                    "default_branch": "main",
                    "permissions": {"admin": True, "push": True, "pull": True}
                }
            ]
        ]
    )
    total: int = Field(description="총 저장소 개수", examples=[1])
    error: Optional[str] = Field(default=None, description="오류 메시지", examples=[None])


class WebhooksListResponse(BaseModel):
    """웹훅 목록 조회 응답"""
    success: bool = Field(description="요청 성공 여부", examples=[True])
    webhooks: List[WebhookInfo] = Field(
        description="웹훅 목록",
        examples=[
            [
                {
                    "id": 12345678,
                    "name": "web",
                    "active": True,
                    "events": ["push", "pull_request"],
                    "config": {"url": "https://api.example.com/webhook", "content_type": "json"}
                }
            ]
        ]
    )
    total: int = Field(description="총 웹훅 개수", examples=[1])
    error: Optional[str] = Field(default=None, description="오류 메시지", examples=[None])


class DeleteWebhookResponse(BaseModel):
    """웹훅 삭제 응답"""
    success: bool = Field(description="요청 성공 여부", examples=[True])
    message: str = Field(description="삭제 결과 메시지", examples=["Webhook deleted successfully."])
    error: Optional[str] = Field(default=None, description="오류 메시지", examples=[None])


class WebhookEventResponse(BaseModel):
    """웹훅 이벤트 처리 응답"""
    success: bool = Field(description="요청 성공 여부", examples=[True])
    message: str = Field(description="처리 결과 메시지", examples=["Event processed successfully"])
    event_type: str = Field(description="이벤트 타입", examples=["push"])
    repository: Optional[str] = Field(default=None, description="관련 저장소", examples=["octocat/Hello-World"])
    processed: bool = Field(default=False, description="처리 여부", examples=[True])
    error: Optional[str] = Field(default=None, description="오류 메시지", examples=[None])


class UserInfo(BaseModel):
    """사용자 상세 정보"""
    user_id: int = Field(description="내부 사용자 아이디", examples=[1])
    github_id: int = Field(description="GitHub 사용자 아이디", examples=[583231])
    username: str = Field(description="GitHub 사용자 이름", examples=["octocat"])
    email: Optional[str] = Field(default=None, description="이메일 주소", examples=["octocat@github.com"])
    avatar_url: Optional[str] = Field(default=None, description="프로필 이미지 URL", examples=["https://avatars.githubusercontent.com/u/583231?v=4"])
    name: Optional[str] = Field(default=None, description="사용자 이름", examples=["The Octocat"])


class UserInfoResponse(BaseModel):
    """사용자 정보 조회 응답"""
    success: bool = Field(description="요청 성공 여부", examples=[True])
    user: Optional[UserInfo] = Field(default=None, description="사용자 상세 정보")
    error: Optional[str] = Field(default=None, description="오류 메시지", examples=[None])
