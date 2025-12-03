"""
# Document Management API

LangGraph 기반 자동 문서 생성 시스템의 문서 관리 API입니다.

## 주요 기능
- **자동 문서 조회**: LangGraph로 생성된 기술 문서 조회
- **클라이언트 편집**: 사용자가 문서를 편집하고 저장
- **문서 목록 관리**: 저장소별, 상태별 문서 필터링 및 검색
- **수동 생성**: 웹훅 실패 시 수동으로 문서 생성 트리거
- **문서 삭제**: 불필요한 문서 정리

## 워크플로우
1. GitHub 코드 변경 → LangGraph 자동 문서 생성
2. 생성된 문서를 클라이언트에서 조회
3. 사용자가 문서 편집 및 개선
4. 편집 완료된 문서 저장
5. 최종 문서 완성

## 문서 상태
- `generated`: LLM으로 자동 생성됨
- `edited`: 사용자가 편집함
- `reviewed`: 검토 완료
- `failed`: 생성 실패
"""

from fastapi import APIRouter, HTTPException, Depends, Query, Body
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime
import os

from .schema import DocumentResponse, DocumentUpdate
from database import get_db
from models import Document, CodeChange, User
from app.logging_config import get_logger

import httpx
import base64
from app.config import GITHUB_API_URL

logger = get_logger("document_router")
router = APIRouter(
    prefix="/documents", 
    tags=["Documents"],
    responses={
        500: {"description": "Internal server error"},
        401: {"description": "Authentication required"},
        403: {"description": "Insufficient permissions"}
    }
)


@router.get(
    "/{document_id}", 
    response_model=DocumentResponse,
    summary="문서 조회",
    description="ID로 특정 문서를 조회합니다. 클라이언트 편집기에서 문서를 로드할 때 사용됩니다.",
    responses={
        200: {
            "description": "문서 조회 성공",
            "content": {
                "application/json": {
                    "example": {
                        "id": 123,
                        "title": "API 변경사항 v1.2.0",
                        "content": "# 주요 변경사항\n\n- 새로운 인증 엔드포인트 추가\n- 기존 API 응답 구조 변경",
                        "summary": "인증 시스템 개선 및 API 구조 변경",
                        "status": "generated",
                        "document_type": "auto",
                        "commit_sha": "a1b2c3d4",
                        "repository_name": "owner/repo",
                        "created_at": "2024-01-15T10:30:00Z",
                        "updated_at": "2024-01-15T10:30:00Z"
                    }
                }
            }
        },
        404: {"description": "문서를 찾을 수 없음"},
        500: {"description": "서버 내부 오류"}
    }
)
async def read_document(document_id: int, db: Session = Depends(get_db)):
    """
    ## 문서 조회
    
    지정된 ID의 문서를 조회합니다.
    
    ### 사용 사례
    - 클라이언트 편집기에서 문서 로드
    - 문서 미리보기
    - 문서 세부정보 확인
    
    ### 주의사항
    - 존재하지 않는 문서 ID를 요청하면 404 오류가 발생합니다
    - 문서의 모든 메타데이터가 포함됩니다
    """
    try:
        document = db.query(Document).filter(Document.id == document_id).first()
        
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        
        logger.info(f"Document retrieved: {document_id}")
        return DocumentResponse.model_validate(document)
        
    except Exception as e:
        logger.error(f"Error retrieving document {document_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch(
    "/{document_id}",
    response_model=DocumentResponse,
    summary="문서 내용 및 상태 업데이트",
    description="""
    사용자가 수정한 문서 내용을 저장하거나 상태를 변경합니다.

    - **Partial Update**: 변경하고 싶은 필드만 골라서 보내면 됩니다.
    - **자동 상태 변경**: `content` 내용만 수정하면 상태가 자동으로 `edited`로 변경됩니다.
    - **수동 상태 변경**: `status` 값을 직접 보내면 그 값이 우선 적용됩니다.
    """,
    responses={
        200: {
            "description": "업데이트 성공",
            "content": {
                "application/json": {
                    "example": {
                        "id": 123,
                        "title": "수정된 제목",
                        "content": "# 수정된 내용...",
                        "status": "edited",
                        "updated_at": "2024-01-15T14:30:00Z"
                    }
                }
            }
        },
        400: {"description": "업데이트할 필드가 없음"},
        404: {"description": "문서를 찾을 수 없음"},
        500: {"description": "서버 내부 오류"}
    }
)
async def update_document(
        document_id: int,
        doc_update: DocumentUpdate = Body(
            ...,
            example={
                "title": "제목만 수정하고 싶을 때",
                "content": "내용만 수정하고 싶을 때 (status는 자동 변경됨)",
                "status": "edited"
            },
            openapi_examples={
                "Title Only": {
                    "summary": "제목만 수정",
                    "description": "제목만 변경하고 싶을 때 사용합니다.",
                    "value": {
                        "title": "새로운 제목 v2"
                    }
                },
                "Content Only": {
                    "summary": "내용만 수정 (자동 상태 변경)",
                    "description": "내용을 수정하면 `status`는 자동으로 `edited`로 바뀝니다.",
                    "value": {
                        "content": "## 수정된 마크다운 내용\n- 여기에 내용을 입력하세요"
                    }
                },
                "Review Complete": {
                    "summary": "검토 완료 처리",
                    "description": "내용 수정 없이 상태만 `reviewed`로 변경합니다.",
                    "value": {
                        "status": "reviewed"
                    }
                },
                "Full Update": {
                    "summary": "전체 수정",
                    "description": "제목, 내용, 상태를 한 번에 수정합니다.",
                    "value": {
                        "title": "최종 수정본",
                        "content": "# 최종 내용...",
                        "status": "reviewed"
                    }
                }
            }
        ),
        db: Session = Depends(get_db)
):
    """
    ### status 필드 사용 가능한 값
    - `generated`: LLM으로 자동 생성된 상태 (기본값)
    - `edited`: 사용자가 편집한 상태
    - `reviewed`: 검토 완료된 상태
    - `failed`: 생성 실패한 상태

    ### 💡 핵심 동작 원리
    1. **필드는 모두 선택(Optional)**입니다.
       - 빈 객체 `{}`를 보내면 400 에러가 납니다. 최소 1개 필드는 보내야 합니다.
    2. **상태 자동 변경 규칙**:
       - `content`를 수정했는데 `status`를 안 보내면 서버가 `status = 'edited'`로 자동 설정.
       - `status`를 직접 보내면 보낸 값(`reviewed` 등)이 그대로 적용됨.
    """
    try:
        # 1. 기존 문서 조회
        document = db.query(Document).filter(Document.id == document_id).first()

        if not document:
            raise HTTPException(status_code=404, detail="Document not found")

        # 2. 업데이트 데이터 준비
        update_data = doc_update.model_dump(exclude_unset=True)

        if not update_data:
            raise HTTPException(status_code=400, detail="No fields to update")

        # 3. 문서 업데이트
        for field, value in update_data.items():
            if hasattr(document, field):
                setattr(document, field, value)

        # 4. content가 변경되면 자동으로 상태를 'edited'로 변경
        if "content" in update_data and "status" not in update_data:
            setattr(document, 'status', 'edited')

        setattr(document, 'updated_at', datetime.utcnow())

        # 5. DB 저장
        db.commit()
        db.refresh(document)

        logger.info(f"Document updated: {document_id}")
        return DocumentResponse.model_validate(document)

    except Exception as e:
        db.rollback()
        logger.error(f"Error updating document {document_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/",
    response_model=List[DocumentResponse],
    summary="문서 목록 조회",
    description="조건에 따라 문서 목록을 조회합니다. 필터링과 페이징을 지원합니다.",
    responses={
        200: {
            "description": "문서 목록 조회 성공",
            "content": {
                "application/json": {
                    "example": [
                        {
                            "id": 123,
                            "title": "API 변경사항 v1.2.0",
                            "content": "# 주요 변경사항...",
                            "status": "generated",
                            "repository_name": "owner/repo",
                            "created_at": "2024-01-15T10:30:00Z"
                        },
                        {
                            "id": 124,
                            "title": "버그 수정 문서",
                            "content": "# 수정된 버그들...",
                            "status": "edited",
                            "repository_name": "owner/repo",
                            "created_at": "2024-01-15T11:00:00Z"
                        }
                    ]
                }
            }
        },
        500: {"description": "서버 내부 오류"}
    }
)
async def list_documents(
    repository_name: Optional[str] = Query(
        None,
        description="저장소 전체 이름 (format: `owner/repo`)",
        example="user/my-project"
    ),
    status: Optional[str] = Query(
        None,
        description="문서 상태",
        enum=["generated", "edited", "reviewed", "failed"],
        example="generated"
    ),
    limit: int = Query(50, ge=1, le=100, description="조회 개수"),
    offset: int = Query(0, ge=0, description="시작 위치"),
    db: Session = Depends(get_db)
):
    """
    ## 문서 목록 조회

    조건에 맞는 문서들의 목록을 조회합니다.

    ### 필터링 옵션
    - **repository_name**: 특정 저장소의 문서만 조회 (예: "owner/repo")
    - **status**: 특정 상태의 문서만 조회
      - `generated`: LLM으로 자동 생성된 문서
      - `edited`: 사용자가 편집한 문서
      - `reviewed`: 검토 완료된 문서
      - `failed`: 생성 실패한 문서

    ### 페이징 옵션
    - **limit**: 한 번에 가져올 문서 수 (기본값: 50, 최대: 100)
    - **offset**: 건너뛸 문서 수 (페이징을 위한 시작점)

    ### 사용 예시
    - 관리자 대시보드에서 전체 문서 목록 확인
    - 특정 저장소의 편집된 문서들만 필터링
    - 페이징으로 대용량 문서 목록 처리

    ### 정렬
    - 최신 생성 순으로 정렬됩니다 (created_at DESC)
    """
    try:
        query = db.query(Document)

        # 필터 적용
        if repository_name:
            query = query.filter(Document.repository_name == repository_name)

        if status:
            query = query.filter(Document.status == status)

        # 정렬 및 페이징
        documents = query.order_by(Document.created_at.desc()).offset(offset).limit(limit).all()

        logger.info(f"Documents listed: {len(documents)} items")
        return [DocumentResponse.model_validate(doc) for doc in documents]

    except Exception as e:
        logger.error(f"Error listing documents: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/trigger/{code_change_id}",
    summary="문서 생성 트리거",
    description="특정 코드 변경사항에 대해 수동으로 문서 생성을 시작합니다.",
    responses={
        200: {
            "description": "문서 생성 성공 또는 기존 문서 존재",
            "content": {
                "application/json": {
                    "examples": {
                        "success": {
                            "summary": "문서 생성 성공",
                            "value": {
                                "message": "Document generation triggered successfully",
                                "document_id": "doc_123",
                                "status": "generated"
                            }
                        },
                        "already_exists": {
                            "summary": "기존 문서 존재",
                            "value": {
                                "message": "Document already exists for this code change",
                                "document_id": 123,
                                "status": "generated"
                            }
                        }
                    }
                }
            }
        },
        404: {"description": "코드 변경사항을 찾을 수 없음"},
        500: {"description": "OpenAI API 키 미설정 또는 서버 오류"},
        501: {"description": "문서 생성 서비스가 아직 구현되지 않음"}
    }
)
async def trigger_document_generation(
    code_change_id: int,
    db: Session = Depends(get_db)
):
    """
    ## 수동 문서 생성 트리거
    
    특정 코드 변경사항(CodeChange)에 대해 LangGraph를 통한 문서 생성을 수동으로 시작합니다.
    
    ### 사용 시나리오
    - GitHub 웹훅이 실패했을 때 수동 복구
    - 기존 코드 변경사항에 대한 문서 재생성
    - 테스트 목적의 문서 생성
    
    ### 처리 과정
    1. 코드 변경사항 존재 확인
    2. 기존 문서 중복 생성 방지 검사
    3. OpenAI API 키 확인
    4. LangGraph 서비스를 통한 문서 생성
    5. 생성된 문서 정보 반환
    
    ### 주의사항
    - 동일한 code_change_id에 대해서는 중복 생성되지 않습니다
    - OPENAI_API_KEY 환경변수가 설정되어 있어야 합니다
    - 생성 과정은 비동기로 진행됩니다
    
    ### 에러 처리
    - 404: 해당 ID의 코드 변경사항이 존재하지 않음
    - 500: API 키 미설정 또는 생성 과정 중 오류 발생
    - 501: 문서 생성 서비스가 아직 구현되지 않음 (개발 중)
    """
    try:
        # 1. 코드 변경사항 확인
        code_change = db.query(CodeChange).filter(CodeChange.id == code_change_id).first()
        
        if not code_change:
            raise HTTPException(status_code=404, detail="CodeChange not found")
        
        # 2. 기존 문서 확인 (중복 생성 방지)
        existing_doc = db.query(Document).filter(Document.code_change_id == code_change_id).first()
        
        if existing_doc:
            return {
                "message": "Document already exists for this code change",
                "document_id": existing_doc.id,
                "status": existing_doc.status
            }
        
        # 3. LangGraph 서비스를 통한 문서 생성
        openai_api_key = os.getenv("OPENAI_API_KEY")
        if not openai_api_key:
            raise HTTPException(status_code=500, detail="OpenAI API key not configured")
        
    
        # 임시로 문서 생성 시뮬레이션
        raise HTTPException(status_code=501, detail="Document generation service not implemented yet")
        doc_service = get_document_service(openai_api_key)
        
        # 4. 문서 생성 실행
        result = doc_service.process_main_branch_changes(
            repository_name=code_change.repository.full_name if code_change.repository else "unknown",
            commit_hash=code_change.commit_sha,
            diff_content="",  # FileChange에서 patch 정보 수집 필요
            changed_files=[fc.filename for fc in code_change.file_changes],
            db=db
        )
        
        if result["success"]:
            return {
                "message": "Document generation triggered successfully",
                "document_id": result["document_id"],
                "status": "generated"
            }
        else:
            raise HTTPException(status_code=500, detail=result["error"])
            
    except Exception as e:
        logger.error(f"Error triggering document generation for CodeChange {code_change_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete(
    "/{document_id}",
    summary="문서 삭제",
    description="지정된 ID의 문서를 영구적으로 삭제합니다.",
    responses={
        200: {
            "description": "문서 삭제 성공",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Document deleted successfully"
                    }
                }
            }
        },
        404: {"description": "문서를 찾을 수 없음"},
        500: {"description": "서버 내부 오류"}
    }
)
async def delete_document(document_id: int, db: Session = Depends(get_db)):
    """
    ## 문서 삭제
    
    지정된 ID의 문서를 데이터베이스에서 영구적으로 삭제합니다.
    
    ### 사용 시나리오
    - 잘못 생성된 문서 제거
    - 더 이상 필요하지 않은 문서 정리
    - 테스트 문서 정리
    
    ### 주의사항
    - **영구 삭제**: 삭제된 문서는 복구할 수 없습니다
    - 트랜잭션 안전성이 보장됩니다
    - 연관된 CodeChange는 삭제되지 않습니다
    
    ### 권장사항
    - 중요한 문서는 삭제 전에 백업을 권장합니다
    - 상태를 'deleted' 등으로 변경하는 soft delete도 고려해보세요
    """
    try:
        document = db.query(Document).filter(Document.id == document_id).first()
        
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        
        db.delete(document)
        db.commit()
        
        logger.info(f"Document deleted: {document_id}")
        return {"message": "Document deleted successfully"}
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting document {document_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/document/latest/{repo_owner}/{repo_name}",
    response_model=DocumentResponse,
    summary="저장소별 최신 문서 조회",
    description="repo_owner와 repo_name에 대해 가장 최근에 수정된 문서 한 건을 반환합니다.",
)
async def get_latest_document(
    repo_owner: str, repo_name: str, db: Session = Depends(get_db)
):
    try:
        repository_full_name = f"{repo_owner}/{repo_name}"
        document = (
            db.query(Document)
            .filter(Document.repository_name == repository_full_name)
            .order_by(Document.updated_at.desc())
            .first()
        )
        if not document:
            raise HTTPException(status_code=404, detail="Document not found for repository")

        logger.info(
            f"Latest document retrieved for repo: {repository_full_name}",
            extra={"repository_name": repository_full_name, "document_id": document.id},
        )
        return DocumentResponse.model_validate(document)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error retrieving latest document for repository {repository_full_name}: {e}",
            extra={"repository_name": repository_full_name},
        )
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/{document_id}/publish",
    summary="GitHub README로 발행",
    description="""
    생성된 문서를 해당 GitHub 저장소의 README.md 파일로 커밋(업로드)합니다. 기존 README.md가 있으면 덮어쓰고(Update), 없으면 새로 만듭니다(Create).
    """,
    responses={
        200: {
            "description": "발행 성공",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Successfully published to owner/repo/README.md",
                        "commit_sha": "7b0a3..."
                    }
                }
            }
        },
        404: {"description": "문서 또는 사용자 토큰을 찾을 수 없음"},
        403: {"description": "GitHub 권한 부족 (쓰기 권한 없음)"}
    }
)
async def publish_document_to_github(
        document_id: int,
        user_id: int = Query(..., description="GitHub에 커밋할 사용자 ID (DB PK)"),
        branch: str = Query("main", description="커밋할 브랜치"),
        message: str = Query("Docs: Update README.md by AutoDoc", description="커밋 메시지"),
        db: Session = Depends(get_db)
):
    try:
        # 1. 문서 조회
        document = db.query(Document).filter(Document.id == document_id).first()
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")

        repo_full_name = document.repository_name  # "owner/repo"

        # 2. 사용자 토큰 조회
        user = db.query(User).filter(User.id == user_id).first()
        if not user or not user.access_token:
            raise HTTPException(status_code=404, detail="User or GitHub token not found")

        access_token = user.access_token

        # 3. GitHub API 호출
        async with httpx.AsyncClient() as client:
            headers = {
                "Authorization": f"token {access_token}",
                "Accept": "application/vnd.github.v3+json"
            }

            file_path = "README.md"
            base_url = "https://api.github.com"
            url = f"{base_url}/repos/{repo_full_name}/contents/{file_path}"

            # 3-1. 기존 파일 확인 (SHA 값 획득용)
            get_response = await client.get(url, headers=headers, params={"ref": branch})
            sha = None

            if get_response.status_code == 200:
                file_data = get_response.json()
                sha = file_data.get("sha")
            elif get_response.status_code == 404:
                pass  # 파일이 없으면 생성
            else:
                # 권한 문제 등 다른 에러
                raise HTTPException(
                    status_code=get_response.status_code,
                    detail=f"Failed to check README: {get_response.text}"
                )

            # 3-2. 파일 내용 인코딩 (GitHub API는 Base64 요구)
            content_bytes = document.content.encode('utf-8')
            content_base64 = base64.b64encode(content_bytes).decode('utf-8')

            # 3-3. PUT 요청 (생성/수정)
            payload = {
                "message": message,
                "content": content_base64,
                "branch": branch
            }
            if sha:
                payload["sha"] = sha  # 업데이트 시 필수

            put_response = await client.put(url, headers=headers, json=payload)

            if put_response.status_code not in [200, 201]:
                error_detail = put_response.json()
                raise HTTPException(
                    status_code=put_response.status_code,
                    detail=f"Commit failed: {error_detail.get('message')}"
                )

            commit_data = put_response.json().get("commit", {})

            logger.info(f"Document {document_id} published to {repo_full_name}")

            return {
                "success": True,
                "message": f"Successfully published to {repo_full_name}/README.md",
                "commit_sha": commit_data.get("sha")
            }

    except Exception as e:
        logger.error(f"Error publishing document {document_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))