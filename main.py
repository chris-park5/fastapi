import sys
import os

# 현재 파일(main.py)이 위치한 디렉토리의 절대 경로를 '동적으로' 알아냅니다.
PROJECT_ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

# sys.path 목록에 계산된 경로를 추가합니다.
if PROJECT_ROOT_DIR not in sys.path:
    sys.path.append(PROJECT_ROOT_DIR)

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from domain.user import git_router
from domain.document import document_router

app = FastAPI()

origins = [
    "http://127.0.0.1:5173",
    "http://localhost:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 등록
app.include_router(git_router.router)
app.include_router(document_router.router)