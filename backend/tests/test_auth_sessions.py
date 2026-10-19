from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.core.auth_sessions import (
    create_user_session,
    find_session_user,
    get_or_create_user,
    revoke_user_session,
)
from app.core.database import Base
from app.models.auth import User, UserSession


def make_database() -> tuple[object, Session]:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return engine, Session(engine)


def test_google_identity_creates_an_account_once_and_updates_profile() -> None:
    engine, db = make_database()
    profile = {
        "sub": "google-sub-1",
        "email": "first@example.com",
        "name": "First Name",
        "picture": "https://example.com/first.png",
        "role": "viewer",
    }

    first_user, created = get_or_create_user(db, profile)
    updated_user, created_again = get_or_create_user(
        db,
        {**profile, "email": "updated@example.com", "name": "Updated Name"},
    )

    assert created is True
    assert created_again is False
    assert first_user.id == updated_user.id
    assert updated_user.email == "updated@example.com"
    assert updated_user.name == "Updated Name"
    assert db.scalar(select(func.count()).select_from(User)) == 1

    db.close()
    engine.dispose()


def test_sessions_are_per_user_and_logout_revokes_only_own_session() -> None:
    engine, db = make_database()
    user_one, _ = get_or_create_user(
        db,
        {"sub": "google-sub-1", "email": "one@example.com", "name": "User One"},
    )
    user_two, _ = get_or_create_user(
        db,
        {"sub": "google-sub-2", "email": "two@example.com", "name": "User Two"},
    )

    token_one = create_user_session(db, user_one)
    token_two = create_user_session(db, user_two)

    assert find_session_user(db, token_one).email == "one@example.com"
    assert find_session_user(db, token_two).email == "two@example.com"
    assert db.scalar(select(func.count()).select_from(UserSession)) == 2

    revoke_user_session(db, token_one)

    assert find_session_user(db, token_one) is None
    assert find_session_user(db, token_two).email == "two@example.com"
    assert db.scalar(select(func.count()).select_from(UserSession)) == 1

    db.close()
    engine.dispose()
