import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.auth import User, UserSession

SESSION_LIFETIME = timedelta(days=30)


def get_or_create_user(db: Session, profile: dict) -> tuple[User, bool]:
    user = db.scalar(select(User).where(User.google_sub == profile["sub"]))
    created = user is None

    if user is None:
        user = User(
            google_sub=profile["sub"],
            email=profile["email"],
            name=profile.get("name", ""),
            picture=profile.get("picture", ""),
            role=profile.get("role", "viewer"),
        )
        db.add(user)
    else:
        user.email = profile["email"]
        user.name = profile.get("name", "")
        user.picture = profile.get("picture", "")

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        user = db.scalar(select(User).where(User.google_sub == profile["sub"]))
        if user is None:
            raise
        user.email = profile["email"]
        user.name = profile.get("name", "")
        user.picture = profile.get("picture", "")
        db.commit()
        created = False

    db.refresh(user)
    return user, created


def create_user_session(db: Session, user: User) -> str:
    now = datetime.now(timezone.utc)
    db.execute(delete(UserSession).where(UserSession.expires_at <= now))

    token = secrets.token_urlsafe(32)
    db.add(
        UserSession(
            token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
            user_id=user.id,
            expires_at=now + SESSION_LIFETIME,
        )
    )
    db.commit()
    return token


def find_session_user(db: Session, token: str | None) -> User | None:
    if not token:
        return None

    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    statement = (
        select(User)
        .join(UserSession)
        .where(
            UserSession.token_hash == token_hash,
            UserSession.expires_at > datetime.now(timezone.utc),
        )
    )
    return db.scalar(statement)


def revoke_user_session(db: Session, token: str | None) -> None:
    if not token:
        return

    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    db.execute(delete(UserSession).where(UserSession.token_hash == token_hash))
    db.commit()


def serialize_user(user: User) -> dict[str, str]:
    return {
        "sub": user.google_sub,
        "email": user.email,
        "name": user.name,
        "picture": user.picture,
        "role": user.role,
    }
