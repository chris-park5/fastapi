import os
from dotenv import load_dotenv

load_dotenv()

GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GITHUB_AUTH_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_API_URL = "https://api.github.com/user"
GITHUB_WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "default_webhook_secret")

# LangGraph/LangChain 문서 생성 모드 (mock 사용 여부)
LANGGRAPH_USE_MOCK = str(os.getenv("LANGGRAPH_USE_MOCK", "false")).lower() in ("1", "true", "yes", "y")