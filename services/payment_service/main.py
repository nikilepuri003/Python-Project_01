import asyncio
import logging
import os
import time
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import BaseModel

FAILURE_MODE = os.getenv("FAILURE_MODE", "healthy")

logger = logging.getLogger("payment-service")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('{"timestamp":"%(asctime)s","level":"%(levelname)s","service":"payment-service","message":"%(message)s"}'))
    logger.addHandler(handler)
logger.propagate = False

resource = Resource.create({"service.name": "payment-service"})
provider = TracerProvider(resource=resource)
provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
trace.set_tracer_provider(provider)
tracer = trace.get_tracer("payment-service")

REQUEST_COUNT = Counter("payment_service_requests_total", "Total payment service HTTP requests", ["method", "path", "status"])
REQUEST_LATENCY = Histogram("payment_service_request_duration_seconds", "Payment service latency in seconds", ["method", "path"])
ERROR_COUNT = Counter("payment_service_errors_total", "Total payment service errors", ["path", "status"])

app = FastAPI(title="Payment Service", version="1.0.0")
FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)


class PaymentRequest(BaseModel):
    user_id: str
    amount: float
    currency: str = "USD"


@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    start_time = time.perf_counter()
    response = await call_next(request)
    latency = time.perf_counter() - start_time
    response.headers["X-Request-ID"] = request_id
    REQUEST_COUNT.labels(request.method, request.url.path, str(response.status_code)).inc()
    REQUEST_LATENCY.labels(request.method, request.url.path).observe(latency)
    if response.status_code >= 400:
        ERROR_COUNT.labels(request.url.path, str(response.status_code)).inc()
    logger.info(f"{request.method} {request.url.path} status={response.status_code} latency_ms={latency * 1000:.2f}", extra={"request_id": request_id})
    return response


@app.get("/health")
def health() -> dict[str, str]:
    logger.info("health check requested")
    return {"status": "healthy", "service": "payment-service"}


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/payments")
async def process_payment(request: Request, payload: PaymentRequest) -> dict[str, Any]:
    headers = {key: value for key, value in request.headers.items()}
    parent_context = TraceContextTextMapPropagator().extract(headers)
    mode = FAILURE_MODE.lower()
    logger.info(f"payment request received user={payload.user_id} amount={payload.amount} mode={mode}")

    with tracer.start_as_current_span("payment_service.process_payment", context=parent_context) as span:
        span.set_attribute("payment.user_id", payload.user_id)
        span.set_attribute("payment.amount", payload.amount)
        span.set_attribute("payment.mode", mode)

        if mode == "unavailable":
            logger.warning("payment mode set to unavailable")
            raise HTTPException(status_code=503, detail={"code": "PAYMENT_UNAVAILABLE", "message": "Payment service is unavailable"})

        if mode == "latency":
            logger.warning("payment mode set to latency")
            with tracer.start_as_current_span("payment_service.database_query"):
                await asyncio.sleep(2.5)

        if mode == "database_timeout":
            logger.warning("payment mode set to database_timeout")
            with tracer.start_as_current_span("payment_service.database_query"):
                await asyncio.sleep(6)
            raise HTTPException(status_code=504, detail={"code": "DATABASE_TIMEOUT", "message": "Database timed out while processing payment"})

        if mode == "timeout":
            logger.warning("payment mode set to timeout")
            with tracer.start_as_current_span("payment_service.database_query"):
                await asyncio.sleep(6)
            raise HTTPException(status_code=504, detail={"code": "PAYMENT_TIMEOUT", "message": "Payment request timed out"})

        result = {
            "status": "approved",
            "payment_id": "pay_demo_456",
            "user_id": payload.user_id,
            "amount": payload.amount,
            "currency": payload.currency,
            "mode": mode,
        }
        logger.info(f"payment approved for user={payload.user_id}")
        return result
