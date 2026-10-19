from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
if "database_url" not in settings.model_fields_set:
    if settings.app_env == "production":
        raise RuntimeError("Production requires a persistent PostgreSQL DATABASE_URL.")
    database_url = "sqlite:///./codepulse.db"
else:
    database_url = settings.database_url

if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql+psycopg://", 1)
elif database_url.startswith("postgresql://"):
    database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)

if settings.app_env == "production" and database_url.startswith("sqlite"):
    raise RuntimeError("Production requires a persistent PostgreSQL DATABASE_URL.")

connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
engine = create_engine(database_url, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def initialize_database() -> None:
    from app.models import Monitor, MonitorCheck, MonitorIncident, User, UserSession

    Base.metadata.create_all(
        bind=engine,
        tables=[
            User.__table__,
            UserSession.__table__,
            Monitor.__table__,
            MonitorCheck.__table__,
            MonitorIncident.__table__,
        ],
    )
