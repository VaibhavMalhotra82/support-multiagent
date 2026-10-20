import hashlib
import hmac
import secrets
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app import db, observability

TOKEN_EXPIRE_MINUTES = 60


def hash_password(password: str) -> str:
    salt = b"support-agent-salt"
    return hashlib.sha256(salt + password.encode("utf-8")).hexdigest()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    salt = b"support-agent-salt"
    candidate = hashlib.sha256(salt + plain_password.encode("utf-8")).hexdigest()
    return hmac.compare_digest(candidate, hashed_password)


def authenticate_user(db_session: Session, username: str, password: str) -> db.User:
    user = db_session.query(db.User).filter(db.User.username == username).first()
    if not user or not verify_password(password, user.hashed_password):
        observability.log_step("auth.authenticate_user", "invalid_credentials", level=30)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user.is_active:
        observability.log_step("auth.authenticate_user", "inactive_user", level=30)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is inactive")
    observability.log_step("auth.authenticate_user", "credentials_verified")
    return user


def create_session_token(db_session: Session, user: db.User) -> db.SessionToken:
    token = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + timedelta(minutes=TOKEN_EXPIRE_MINUTES)
    session_token = db.SessionToken(token=token, user_id=user.id, expires_at=expires_at)
    db_session.add(session_token)
    db_session.commit()
    db_session.refresh(session_token)
    observability.log_step("auth.create_session_token", "session_token_created")
    return session_token


def get_user_from_token(db_session: Session, token: str) -> Optional[db.User]:
    session_token = (
        db_session.query(db.SessionToken)
        .filter(db.SessionToken.token == token)
        .filter(db.SessionToken.expires_at >= datetime.utcnow())
        .filter(db.SessionToken.revoked_at.is_(None))
        .first()
    )
    if not session_token:
        observability.log_step("auth.get_user_from_token", "invalid_or_expired_token", level=30)
        return None
    observability.log_step("auth.get_user_from_token", "token_valid")
    return session_token.user


def revoke_user_sessions(db_session: Session, user_id: int) -> int:
    active_tokens = (
        db_session.query(db.SessionToken)
        .filter(db.SessionToken.user_id == user_id)
        .filter(db.SessionToken.revoked_at.is_(None))
        .all()
    )
    if not active_tokens:
        observability.log_step("auth.revoke_user_sessions", "no_active_sessions", level=30)
        return 0

    revoked_at = datetime.utcnow()
    for session_token in active_tokens:
        session_token.revoked_at = revoked_at
    db_session.commit()
    observability.log_step("auth.revoke_user_sessions", f"sessions_revoked={len(active_tokens)}")
    return len(active_tokens)


def user_has_permission(user: db.User, permission_name: str) -> bool:
    permissions = [permission.name for role in user.roles for permission in role.permissions]
    return permission_name in permissions


def assert_permission(user: db.User, permission_name: str) -> None:
    if not user_has_permission(user, permission_name):
        observability.log_step("auth.assert_permission", f"permission_denied permission={permission_name}", level=30)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    observability.log_step("auth.assert_permission", f"permission_granted permission={permission_name}")
