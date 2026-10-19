from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.auth import User


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Monitor(Base):
    __tablename__ = "monitors"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    url: Mapped[str] = mapped_column(String(2048))
    interval_seconds: Mapped[int] = mapped_column(Integer, default=300)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    next_check_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utc_now, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utc_now, onupdate=utc_now)

    user: Mapped["User"] = relationship(back_populates="monitors")
    checks: Mapped[list["MonitorCheck"]] = relationship(cascade="all, delete-orphan")
    incidents: Mapped[list["MonitorIncident"]] = relationship(cascade="all, delete-orphan")


class MonitorCheck(Base):
    __tablename__ = "monitor_checks"

    id: Mapped[int] = mapped_column(primary_key=True)
    monitor_id: Mapped[int] = mapped_column(ForeignKey("monitors.id", ondelete="CASCADE"), index=True)
    result: Mapped[str] = mapped_column(String(32), index=True)
    reachable: Mapped[bool] = mapped_column(Boolean)
    status_code: Mapped[Any] = mapped_column(Integer, nullable=True)
    response_time_ms: Mapped[float] = mapped_column(Float)
    message: Mapped[str] = mapped_column(Text)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utc_now, index=True)


class MonitorIncident(Base):
    __tablename__ = "monitor_incidents"

    id: Mapped[int] = mapped_column(primary_key=True)
    monitor_id: Mapped[int] = mapped_column(ForeignKey("monitors.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    severity: Mapped[str] = mapped_column(String(16), default="medium")
    title: Mapped[str] = mapped_column(String(255))
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON)
    diagnosis: Mapped[Any] = mapped_column(JSON, nullable=True)
    diagnosis_provider: Mapped[Any] = mapped_column(String(32), nullable=True)
    patch_proposal: Mapped[Any] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utc_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utc_now, onupdate=utc_now)
    resolved_at: Mapped[Any] = mapped_column(DateTime(timezone=False), nullable=True)
