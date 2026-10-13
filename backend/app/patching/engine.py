from __future__ import annotations

from dataclasses import dataclass, field
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
    """Generate a minimal patch proposal for a detected incident."""

    def generate(self, incident: dict[str, Any], diagnosis: dict[str, Any]) -> PatchProposal:
        service = str(incident.get("service") or "unknown-service")
        evidence = incident.get("evidence") or {}
        error_rate = float(evidence.get("error_rate", 0.0) or 0.0)
        timeout_rate = float(evidence.get("timeout_rate", 0.0) or 0.0)
        latency_ms = float(evidence.get("p95_latency_ms", 0.0) or 0.0)

        file_path = "services/payment_service/main.py"
        if "order" in service.lower():
            file_path = "services/order_service/main.py"
        elif "user" in service.lower():
            file_path = "services/user_service/main.py"

        summary = (
            f"Guard against dependency timeout and latency for {service} by adding a cautious timeout "
            "and fallback path before the dependency gets retried."
        )

        diff = f"""
--- a/{file_path}
+++ b/{file_path}
@@
-    if mode == "database_timeout":
-        logger.warning("payment mode set to database_timeout")
-        with tracer.start_as_current_span("payment_service.database_query"):
-            await asyncio.sleep(6)
-        raise HTTPException(status_code=504, detail={{"code": "DATABASE_TIMEOUT", "message": "Database timed out while processing payment"}})
+    if mode == "database_timeout":
+        logger.warning("payment mode set to database_timeout")
+        with tracer.start_as_current_span("payment_service.database_query"):
+            await asyncio.sleep(2)
+        return {{
+            "status": "queued",
+            "payment_id": "pay_demo_456",
+            "message": "Payment request accepted but queued for retry due to dependency delay.",
+        }}
+
+    if mode == "timeout":
+        logger.warning("payment mode set to timeout")
+        with tracer.start_as_current_span("payment_service.database_query"):
+            await asyncio.sleep(2)
+        return {{
+            "status": "queued",
+            "payment_id": "pay_demo_456",
+            "message": "Payment request accepted but queued for retry due to dependency delay.",
+        }}
+"""

        if service.lower() == "user-service":
            diff = f"""
--- a/{file_path}
+++ b/{file_path}
@@
-    logger.info("health check requested")
-    return {{"status": "healthy", "service": "user-service"}}
+    logger.info("health check requested")
+    return {{"status": "healthy", "service": "user-service", "checks": ["database", "http"]}}
+"""

        risks = [
            "This is a minimal prototype patch and should be reviewed by a human before deployment.",
            "Retry queueing may change user-visible latency under pressure.",
        ]

        confidence = 0.85
        if error_rate < 0.2 and timeout_rate < 0.1 and latency_ms < 1500:
            confidence = 0.7

        return PatchProposal(
            id=f"patch-{service.lower().replace('-', '')}",
            service=service,
            summary=summary,
            file_path=file_path,
            diff=diff,
            confidence=confidence,
            risks=risks,
        )
