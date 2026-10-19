from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
import threading
import time
import uuid

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from app.api.v1.routes import router as v1_router
from app.core.config import get_settings
from app.core.database import engine, initialize_database
from app.core.logging import get_logger
from app.services.monitoring import run_due_checks

settings = get_settings()
logger = get_logger("codepulse.backend", service="backend")

resource = Resource.create({"service.name": "codepulse-backend"})
provider = TracerProvider(resource=resource)
provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
trace.set_tracer_provider(provider)

REQUEST_COUNT = Counter("codepulse_backend_http_requests_total", "Total backend HTTP requests", ["method", "path", "status"])
REQUEST_LATENCY = Histogram("codepulse_backend_http_request_duration_seconds", "Backend request latency in seconds", ["method", "path"])
ERROR_COUNT = Counter("codepulse_backend_http_errors_total", "Total backend errors", ["path", "status"])


def start_monitor_scheduler() -> tuple[threading.Event, threading.Thread] | None:
    if not settings.monitor_scheduler_enabled:
        logger.info("Monitor scheduler disabled by configuration")
        return None

    stop_event = threading.Event()

    def scheduler_loop() -> None:
        lock_connection = None
        try:
            if engine.dialect.name == "postgresql":
                lock_connection = engine.connect()
                acquired = bool(
                    lock_connection.exec_driver_sql(
                        "SELECT pg_try_advisory_lock(7362149051)"
                    ).scalar()
                )
                lock_connection.commit()
                if not acquired:
                    logger.info("Another backend instance owns the monitor scheduler")
                    return
            while not stop_event.is_set():
                try:
                    count = run_due_checks(stop_event=stop_event)
                    if count:
                        logger.info("Scheduled monitor checks completed: %s", count)
                except Exception:
                    logger.exception("Scheduled monitor check batch failed")
                stop_event.wait(5)
        except Exception:
            logger.exception("Monitor scheduler could not acquire its database lock")
        finally:
            if lock_connection is not None:
                try:
                    lock_connection.exec_driver_sql(
                        "SELECT pg_advisory_unlock(7362149051)"
                    )
                    lock_connection.commit()
                except Exception:
                    logger.exception("Could not release monitor scheduler lock")
                finally:
                    lock_connection.close()

    scheduler_thread = threading.Thread(
        target=scheduler_loop,
        name="codepulse-monitor-scheduler",
        daemon=True,
    )
    scheduler_thread.start()
    return stop_event, scheduler_thread


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None, None]:
    initialize_database()
    scheduler = start_monitor_scheduler()
    application.state.monitor_scheduler_enabled = scheduler is not None
    try:
        yield
    finally:
        if scheduler is not None:
            stop_event, scheduler_thread = scheduler
            stop_event.set()
            scheduler_thread.join(timeout=15)


app = FastAPI(
    title="CodePulse AI API",
    version="0.1.0",
    description="Observability and AI-assisted incident response backend for the CodePulse MVP.",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

frontend_origin = settings.frontend_url.rstrip("/")
if not frontend_origin.startswith(("http://", "https://")):
    frontend_origin = f"https://{frontend_origin}"

app.add_middleware(
    CORSMiddleware,
    allow_origins=[frontend_origin, "http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
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
    if response.status_code >= 400:
        ERROR_COUNT.labels(request.url.path, str(response.status_code)).inc()

    logger.info(
        f"{request.method} {request.url.path} status={response.status_code} latency_ms={latency * 1000:.2f}",
        extra={"request_id": request_id, "endpoint": request.url.path, "status_code": response.status_code},
    )
    return response


@app.get("/health")
def health() -> dict[str, str]:
    logger.info("Health endpoint called", extra={"service": "backend"})
    return {"status": "ok", "service": "backend"}


@app.get("/ready")
def ready() -> dict[str, str]:
    return {"status": "ready"}


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


app.include_router(v1_router)


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "CodePulse AI backend is running"}
