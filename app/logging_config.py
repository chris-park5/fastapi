import logging
import sys
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, Union


# 로깅 설정 모듈

class ColoredFormatter(logging.Formatter):
    """컬러 포맷터 (콘솔용)"""

    COLORS = {
        'DEBUG': '\033[36m',  # 청록색
        'INFO': '\033[32m',  # 녹색
        'WARNING': '\033[33m',  # 노란색
        'ERROR': '\033[31m',  # 빨간색
        'CRITICAL': '\033[35m'  # 자주색
    }
    RESET = '\033[0m'

    def format(self, record):
        log_color = self.COLORS.get(record.levelname, self.RESET)
        record.levelname = f"{log_color}{record.levelname}{self.RESET}"
        return super().format(record)


def setup_logging(log_level: str = "INFO", log_file: Optional[str] = None) -> logging.Logger:
    """
    로깅 시스템 설정

    Args:
        log_level: 로그 레벨 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: 로그 파일 경로 (기본: logs/app.log)

    Returns:
        설정된 로거
    """
    # 로그 레벨 설정
    level = getattr(logging, log_level.upper(), logging.INFO)

    # 로그 디렉토리 생성
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    # 기본 로그 파일명
    if not log_file:
        log_file = str(log_dir / f"app_{datetime.now().strftime('%Y%m%d')}.log")

    # 로거 설정
    logger = logging.getLogger("CICDAutoDoc")
    logger.setLevel(level)

    # 기존 핸들러 제거 (중복 방지)
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    # 포맷터 설정
    file_formatter = logging.Formatter(
        fmt='%(asctime)s - %(name)s - %(levelname)s - %(module)s:%(lineno)d - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    console_formatter = ColoredFormatter(
        fmt='%(asctime)s - %(levelname)s - %(module)s:%(lineno)d - %(message)s',
        datefmt='%H:%M:%S'
    )

    # 파일 핸들러 (모든 로그)
    try:
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)
    except Exception as e:
        print(f"Warning: Failed to setup file logging: {e}")

    # 콘솔 핸들러
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    # 초기 로그
    logger.info("Logging system initialized", extra={
        "log_level": log_level,
        "log_file": str(log_file),
        "handlers": len(logger.handlers)
    })

    return logger


# 전역 로거 인스턴스
_logger = None


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """
    로거 인스턴스 반환

    Args:
        name: 로거 이름 (모듈명 등)

    Returns:
        로거 인스턴스
    """
    global _logger
    if _logger is None:
        _logger = setup_logging()

    if name:
        return _logger.getChild(name)
    return _logger


# 편의 함수들
def log_webhook_event(event_type: str, repository: str, **kwargs):
    """웹훅 이벤트 로깅"""
    logger = get_logger("webhook")
    logger.info(f"Webhook received: {event_type}", extra={
        "event_type": event_type,
        "repository": repository,
        **kwargs
    })


def log_document_generation(code_change_id: int, status: str, **kwargs):
    """문서 생성 로깅"""
    logger = get_logger("document")
    logger.info(f"Document generation {status}", extra={
        "code_change_id": code_change_id,
        "status": status,
        **kwargs
    })


def log_github_api_call(url: str, status_code: int, **kwargs):
    """GitHub API 호출 로깅"""
    logger = get_logger("github_api")
    logger.info(f"GitHub API call: {status_code}", extra={
        "url": url,
        "status_code": status_code,
        **kwargs
    })


def log_error(message: str, error: Optional[Exception] = None, **kwargs):
    """에러 로깅"""
    logger = get_logger("error")
    if error:
        logger.error(f"{message}: {str(error)}", extra={
            "error_type": type(error).__name__,
            "error_message": str(error),
            **kwargs
        }, exc_info=True)
    else:
        logger.error(message, extra=kwargs)


# 개발환경용 설정
def setup_development_logging():
    """개발환경용 상세 로깅"""
    return setup_logging(log_level="DEBUG")


# 프로덕션용 설정
def setup_production_logging():
    """프로덕션용 간소 로깅"""
    return setup_logging(log_level="INFO")


# 환경변수 기반 자동 설정
def setup_logging_from_env():
    """환경변수를 기반으로 로깅 설정"""
    log_level = os.getenv("LOG_LEVEL", "INFO")
    log_file = os.getenv("LOG_FILE")
    return setup_logging(log_level, log_file)