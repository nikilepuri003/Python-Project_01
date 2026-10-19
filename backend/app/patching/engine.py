from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class PatchProposal:
    id: str
    service: str
    summary: str
    file_path: str
    diff: str
    confidence: float = 0.0
    risks: list[str] = field(default_factory=list)
    validation_status: str = "pending"


class PatchGenerator:
    """Build the reviewed demo payment-service patch from its checked-in source."""

    FILE_PATH = "services/payment_service/main.py"
    OLD_BLOCK = '''        if mode == "database_timeout":
            logger.warning("payment mode set to database_timeout")
            with tracer.start_as_current_span("payment_service.database_query"):
                await asyncio.sleep(6)
            raise HTTPException(status_code=504, detail={"code": "DATABASE_TIMEOUT", "message": "Database timed out while processing payment"})
'''
    NEW_BLOCK = '''        if mode == "database_timeout":
            logger.warning("payment mode set to database_timeout")
            with tracer.start_as_current_span("payment_service.database_query"):
                await asyncio.sleep(2)
            return {
                "status": "queued",
                "payment_id": "pay_demo_456",
                "message": "Payment request accepted but queued for retry due to dependency delay.",
            }
'''

    def generate(
        self,
        incident: dict[str, Any],
        diagnosis: dict[str, Any],
        project_root: str | Path | None = None,
    ) -> PatchProposal:
        service = str(incident.get("service") or "").strip().lower()
        if service not in {"payment-service", "payment service"}:
            raise ValueError("Patch proposals are currently supported only for the included payment-service demo.")

        root = Path(project_root).resolve() if project_root else Path(__file__).resolve().parents[3]
        target = root / self.FILE_PATH
        if not target.is_file() or target.is_symlink():
            raise ValueError("The approved payment-service demo source is unavailable in this deployment.")
        current_source = target.read_text(encoding="utf-8")
        if current_source.count(self.OLD_BLOCK) == 1 and self.NEW_BLOCK not in current_source:
            original = current_source
        elif current_source.count(self.NEW_BLOCK) == 1 and self.OLD_BLOCK not in current_source:
            original = current_source.replace(self.NEW_BLOCK, self.OLD_BLOCK, 1)
        else:
            raise ValueError("The payment-service source differs from the reviewed patch template.")
        updated = original.replace(self.OLD_BLOCK, self.NEW_BLOCK, 1)
        diff = "".join(
            difflib.unified_diff(
                original.splitlines(keepends=True),
                updated.splitlines(keepends=True),
                fromfile=f"a/{self.FILE_PATH}",
                tofile=f"b/{self.FILE_PATH}",
                n=3,
            )
        )

        return PatchProposal(
            id="payment-database-timeout-queue-fallback",
            service="payment-service",
            summary="Queue payment requests when the demo database dependency times out.",
            file_path=self.FILE_PATH,
            diff=diff,
            confidence=0.7,
            risks=[
                "Changes the demo API response from HTTP 504 to an accepted queued response.",
                "This proposal is specific to the included demo service; production semantics require human review.",
            ],
        )
