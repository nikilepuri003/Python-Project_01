import logging
import time
import uuid

from fastapi import FastAPI, Request, Response
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

logger = logging.getLogger("user-service")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('{"timestamp":"%(asctime)s","level":"%(levelname)s","service":"user-service","message":"%(message)s"}'))
    logger.addHandler(handler)
logger.propagate = False

resource = Resource.create({"service.name": "user-service"})
provider = TracerProvider(resource=resource)
provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
trace.set_tracer_provider(provider)

REQUEST_COUNT = Counter("user_service_requests_total", "Total HTTP requests", ["method", "path", "status"])
REQUEST_LATENCY = Histogram("user_service_request_duration_seconds", "User service request latency in seconds", ["method", "path"])

app = FastAPI(title="User Service", version="1.0.0")
FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)


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
    return {"status": "healthy", "service": "user-service"}


@app.get("/users/{user_id}")
def get_user(user_id: str) -> dict[str, object]:
    logger.info(f"user lookup requested for {user_id}")
    return {
        "id": user_id,
        "name": "Demo User",
        "email": "demo.user@example.com",
        "status": "active",
    }


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
