from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean, JSON
from sqlalchemy.orm import relationship
from datetime import datetime, timezone

from database import Base


# GitHub 관련 모델들
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    github_id = Column(Integer, unique=True, nullable=False)
    username = Column(String(100), nullable=False)
    email = Column(String(255))
    access_token = Column(Text)  # 암호화해서 저장 필요
    created_at = Column(DateTime, default=datetime.utcnow)

    # 관계 설정
    repositories = relationship("Repository", back_populates="owner")


class Repository(Base):
    __tablename__ = "repositories"

    id = Column(Integer, primary_key=True)
    github_id = Column(Integer, unique=True, nullable=False)
    name = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=False)
    default_branch = Column(String(100), default="main")
    is_private = Column(Boolean, default=False)
    owner_id = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)

    # 관계 설정
    owner = relationship("User", back_populates="repositories")
    webhook_registrations = relationship("WebhookRegistration", back_populates="repository")
    code_changes = relationship("CodeChange", back_populates="repository")


class WebhookRegistration(Base):
    __tablename__ = "webhook_registrations"

    id = Column(Integer, primary_key=True)
    repo_owner = Column(String(100), nullable=False)
    repo_name = Column(String(255), nullable=False)
    webhook_id = Column(Integer, unique=True, nullable=False)
    webhook_url = Column(Text, nullable=False)
    access_token = Column(Text)  # 암호화해서 저장 필요
    is_active = Column(Boolean, default=True)
    repository_id = Column(Integer, ForeignKey("repositories.id"))
    created_at = Column(DateTime, default=datetime.utcnow)

    # 관계 설정
    repository = relationship("Repository", back_populates="webhook_registrations")


class CodeChange(Base):
    __tablename__ = "code_changes"

    id = Column(Integer, primary_key=True)
    commit_sha = Column(String(40), nullable=False)
    commit_message = Column(Text)
    author_name = Column(String(100))
    author_email = Column(String(255))
    repository_id = Column(Integer, ForeignKey("repositories.id"))
    source = Column(String(20))  # "push" or "pr_merge"
    total_changes = Column(Integer, default=0)
    timestamp = Column(DateTime, default=datetime.utcnow)

    # 관계 설정
    repository = relationship("Repository", back_populates="code_changes")
    file_changes = relationship("FileChange", back_populates="code_change")
    document = relationship("Document", back_populates="code_change", uselist=False)


class FileChange(Base):
    __tablename__ = "file_changes"

    id = Column(Integer, primary_key=True)
    filename = Column(Text, nullable=False)
    status = Column(String(20))  # "added", "modified", "removed"
    changes = Column(Integer, default=0)
    additions = Column(Integer, default=0)
    deletions = Column(Integer, default=0)
    patch = Column(Text)  # diff patch text from GitHub (optional)
    code_change_id = Column(Integer, ForeignKey("code_changes.id"))

    # 관계 설정
    code_change = relationship("CodeChange", back_populates="file_changes")


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True)
    title = Column(String(500), nullable=False)
    content = Column(Text, nullable=False)
    summary = Column(Text)  # 문서 요약
    status = Column(String(20), default="generated")  # "generated", "failed", "updating"
    document_type = Column(String(50), default="auto")  # "auto", "manual", "merged"
    commit_sha = Column(String(40), nullable=False, unique=True)  # 중복 방지
    repository_name = Column(String(255))
    generation_metadata = Column(JSON)  # LLM 처리 메타데이터
    code_change_id = Column(Integer, ForeignKey("code_changes.id"))
    created_at = Column(DateTime, default=datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))

    # 관계 설정
    code_change = relationship("CodeChange", back_populates="document")