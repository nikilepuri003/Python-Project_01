from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field, ValidationError


class AIDiagnosis(BaseModel):
    root_cause: str
    evidence: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    affected_components: list[str] = Field(default_factory=list)
    recommended_fix: str = ""
    files_to_change: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)

    @classmethod
    def from_any(cls, payload: Any) -> "AIDiagnosis":
        if isinstance(payload, cls):
            return payload
        if not isinstance(payload, dict):
            raise ValidationError.from_exception_data(cls.__name__, [{"type": "dict_type", "loc": (), "msg": "Expected a dictionary"}])
        return cls.model_validate(payload)


class AIProvider(ABC):
    """Abstract interface for AI-backed incident diagnosis providers."""

    @abstractmethod
    def diagnose(self, incident: dict[str, Any], evidence: dict[str, Any] | None = None) -> AIDiagnosis:
        raise NotImplementedError
