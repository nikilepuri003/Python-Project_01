import logging
import os
import time
import uuid
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import BaseModel

PAYMENT_SERVICE_URL = os.getenv("PAYMENT_SERVICE_URL", "http://127.0.0.1:8003")

logger = logging.getLogger("order-service")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('{"timestamp":"%(asctime)s","level":"%(levelname)s","service":"order-service","message":"%(message)s"}'))
    logger.addHandler(handler)
logger.propagate = False

resource = Resource.create({"service.name": "order-service"})
provider = TracerProvider(resource=resource)
provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
trace.set_tracer_provider(provider)
tracer = trace.get_tracer("order-service")

REQUEST_COUNT = Counter("order_service_requests_total", "Total order service HTTP requests", ["method", "path", "status"])
REQUEST_LATENCY = Histogram("order_service_request_duration_seconds", "Order service latency in seconds", ["method", "path"])
DEPENDENCY_FAILURES = Counter("order_service_dependency_failures_total", "Total dependency call failures", ["dependency", "status"])

app = FastAPI(title="Order Service", version="1.0.0")
FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)


class OrderRequest(BaseModel):
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
    logger.info(f"{request.method} {request.url.path} status={response.status_code} latency_ms={latency * 1000:.2f}", extra={"request_id": request_id})
    return response


@app.get("/health")
def health() -> dict[str, str]:
    logger.info("health check requested")
    return {"status": "healthy", "service": "order-service"}


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/orders")
async def create_order(payload: OrderRequest) -> dict[str, Any]:
    logger.info(f"creating order for user={payload.user_id} amount={payload.amount}")
    try:
        with tracer.start_as_current_span("order_service.call_payment") as span:
            span.set_attribute("order.user_id", payload.user_id)
            span.set_attribute("order.amount", payload.amount)
            headers = {}
            TraceContextTextMapPropagator().inject(headers)
            async with httpx.AsyncClient(timeout=5.0) as client:
                payment_response = await client.post(
                    f"{PAYMENT_SERVICE_URL}/payments",
                    json={"user_id": payload.user_id, "amount": payload.amount, "currency": payload.currency},
                    headers=headers,
                )
    except httpx.TimeoutException as exc:
        DEPENDENCY_FAILURES.labels("payment-service", "504").inc()
        logger.warning("payment dependency timed out", extra={"dependency": "payment-service"})
        raise HTTPException(status_code=504, detail={"error": {"code": "PAYMENT_TIMEOUT", "message": "Payment service timed out"}}) from exc
    except httpx.HTTPError as exc:
        DEPENDENCY_FAILURES.labels("payment-service", "503").inc()
        logger.warning("payment dependency unavailable", extra={"dependency": "payment-service"})
        raise HTTPException(status_code=503, detail={"error": {"code": "PAYMENT_UNAVAILABLE", "message": "Payment service unavailable"}}) from exc

    if payment_response.status_code >= 500:
        DEPENDENCY_FAILURES.labels("payment-service", str(payment_response.status_code)).inc()
        logger.warning(f"payment service returned server error {payment_response.status_code}")
        raise HTTPException(
            status_code=503,
            detail={
                "error": {
                    "code": "PAYMENT_SERVICE_FAILURE",
                    "message": payment_response.json().get("detail", {}).get("message", "Payment service failed"),
                }
            },
        )

    if payment_response.status_code >= 400:
        logger.warning(f"payment service rejected request with {payment_response.status_code}")
        raise HTTPException(status_code=400, detail={"error": {"code": "PAYMENT_REJECTED", "message": "Payment request was rejected"}})

    result = {
        "order_id": "ord_demo_123",
        "status": "created",
        "user_id": payload.user_id,
        "payment_status": payment_response.json().get("status"),
        "amount": payload.amount,
        "currency": payload.currency,
    }
    logger.info(f"order created successfully for user={payload.user_id}")
    return result
