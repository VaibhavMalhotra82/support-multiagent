from datetime import datetime
from typing import List

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    create_engine,
    Index,
    func,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session, relationship, sessionmaker

from app.config import settings


DATABASE_URL = settings.database_url

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id"), primary_key=True),
    Column("role_id", Integer, ForeignKey("roles.id"), primary_key=True),
)

role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", Integer, ForeignKey("roles.id"), primary_key=True),
    Column("permission_id", Integer, ForeignKey("permissions.id"), primary_key=True),
)


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)
    description = Column(Text, nullable=True)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=True)

    tenant = relationship("Tenant")
    roles = relationship("Role", secondary=user_roles, back_populates="users")


class Role(Base):
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)
    description = Column(Text, nullable=True)

    users = relationship("User", secondary=user_roles, back_populates="roles")
    permissions = relationship("Permission", secondary=role_permissions, back_populates="roles")


class Permission(Base):
    __tablename__ = "permissions"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)
    description = Column(Text, nullable=True)

    roles = relationship("Role", secondary=role_permissions, back_populates="permissions")


class SessionToken(Base):
    __tablename__ = "session_tokens"

    id = Column(Integer, primary_key=True, index=True)
    token = Column(String, unique=True, index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    revoked_at = Column(DateTime, nullable=True, index=True)

    user = relationship("User")


class RootCauseAnalysis(Base):
    __tablename__ = "root_cause_analysis"

    id = Column(Integer, primary_key=True, index=True)
    symptom = Column(Text, nullable=False)
    root_cause = Column(Text, nullable=False)
    resolution = Column(Text, nullable=False)
    product = Column(String, nullable=True)
    version = Column(String, nullable=True)
    tags = Column(Text, nullable=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    tenant = relationship("Tenant")


class Feedback(Base):
    __tablename__ = "feedback"

    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(String, nullable=False)
    helpful = Column(Boolean, nullable=False)
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class QueryRecord(Base):
    __tablename__ = "query_records"

    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(String, unique=True, index=True, nullable=False)
    session_id = Column(String, index=True, nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    resolved = Column(Boolean, nullable=False, default=True)
    cache_hit = Column(Boolean, nullable=False, default=False)
    should_escalate = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, server_default=func.now())

    user = relationship("User")


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String, index=True, nullable=False)
    request_id = Column(String, index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=True)
    role = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    metadata_json = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    user = relationship("User")
    tenant = relationship("Tenant")


Index(
    "ix_conversation_messages_owner_session",
    ConversationMessage.user_id,
    ConversationMessage.tenant_id,
    ConversationMessage.session_id,
    ConversationMessage.created_at,
)


class LongTermMemoryRecord(Base):
    __tablename__ = "long_term_memory_records"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String, index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=True)
    summary = Column(Text, nullable=False)
    metadata_json = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    user = relationship("User")
    tenant = relationship("Tenant")


Index(
    "ix_long_term_memory_owner",
    LongTermMemoryRecord.user_id,
    LongTermMemoryRecord.tenant_id,
    LongTermMemoryRecord.created_at,
)


class Escalation(Base):
    __tablename__ = "escalations"

    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(String, unique=True, index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    reason = Column(Text, nullable=True)
    status = Column(String, nullable=False, default="open")
    created_at = Column(DateTime, server_default=func.now())

    user = relationship("User")


class ActivityEvent(Base):
    __tablename__ = "activity_events"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    event_type = Column(String, nullable=False, index=True)
    description = Column(Text, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False, index=True)

    user = relationship("User")


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    if DATABASE_URL.startswith("sqlite"):
        with engine.begin() as connection:
            columns = {
                row[1]
                for row in connection.exec_driver_sql("PRAGMA table_info(query_records)").fetchall()
            }
            if "session_id" not in columns:
                connection.exec_driver_sql("ALTER TABLE query_records ADD COLUMN session_id VARCHAR")
            token_columns = {
                row[1]
                for row in connection.exec_driver_sql("PRAGMA table_info(session_tokens)").fetchall()
            }
            if "revoked_at" not in token_columns:
                connection.exec_driver_sql("ALTER TABLE session_tokens ADD COLUMN revoked_at DATETIME")


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
