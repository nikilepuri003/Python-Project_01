from __future__ import annotations

import http.client
import ipaddress
import logging
import socket
import ssl
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit, urlunsplit

from prometheus_client import Counter, Histogram
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.monitoring import Monitor, MonitorCheck, MonitorIncident

logger = logging.getLogger("codepulse.monitoring")

CHECKS_TOTAL = Counter(
    "codepulse_monitor_checks_total",
    "Completed scheduled and manual monitor checks.",
    ["result"],
)
CHECK_DURATION = Histogram(
    "codepulse_monitor_check_duration_seconds",
    "Duration of monitor checks in seconds.",
)
INCIDENTS_CREATED = Counter(
    "codepulse_monitor_incidents_created_total",
    "Number of monitor incidents created.",
)

MAX_MONITORS_PER_USER = 20
MAX_CHECKS_PER_MONITOR = 1000
MAX_RESOLVED_INCIDENTS_PER_MONITOR = 100
RESOLVED_INCIDENT_RETENTION = timedelta(days=90)
MIN_INTERVAL_SECONDS = 60
MAX_INTERVAL_SECONDS = 86_400
DEMO_SERVICE_TARGETS = {
    "payment-service": ("payment-service", 8003),
    "order-service": ("order-service", 8002),
    "user-service": ("user-service", 8001),
}


@dataclass(frozen=True)
class ValidatedURL:
    url: str
    hostname: str
    port: int
    scheme: str
    request_target: str
    host_header: str
    addresses: tuple[str, ...]


def validate_public_url(raw_url: str) -> ValidatedURL:
    if len(raw_url) > 2048:
        raise ValueError("Website URL must be 2048 characters or fewer.")
    candidate = raw_url.strip()
    if not candidate:
        raise ValueError("Enter a website URL to check.")
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    try:
        parsed = urlsplit(candidate)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Enter a valid website URL.") from exc

    scheme = parsed.scheme.lower()
    hostname = parsed.hostname
    port = port or (443 if scheme == "https" else 80)
    if (
        scheme not in {"http", "https"}
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or port not in {80, 443}
        or hostname.endswith(".")
        or any(ord(character) < 32 for character in candidate)
        or any(ord(character) == 127 for character in candidate)
    ):
        raise ValueError("Use a public website URL with HTTP or HTTPS on port 80 or 443.")

    try:
        try:
            addresses = (ipaddress.ip_address(hostname),)
        except ValueError:
            address_infos = socket.getaddrinfo(
                hostname,
                port,
                type=socket.SOCK_STREAM,
            )
            addresses = tuple({ipaddress.ip_address(info[4][0]) for info in address_infos})
    except (OSError, ValueError) as exc:
        raise ValueError("The website hostname could not be resolved.") from exc

    if not addresses or any(not address.is_global for address in addresses):
        raise ValueError("Only publicly accessible websites can be checked.")

    host_header = parsed.netloc
    path = parsed.path or "/"
    request_target = urlunsplit(("", "", path, parsed.query, ""))
    normalized_url = urlunsplit((scheme, parsed.netloc, path, parsed.query, ""))
    return ValidatedURL(
        url=normalized_url,
        hostname=hostname,
        port=port,
        scheme=scheme,
        request_target=request_target,
        host_header=host_header,
        addresses=tuple(str(address) for address in addresses),
    )


def get_demo_monitor_services() -> list[dict[str, str]]:
    return [
        {
            "id": service_id,
            "name": service_id.replace("-", " ").title(),
            "url": f"demo://{service_id}",
        }
        for service_id in DEMO_SERVICE_TARGETS
    ]


def validate_monitor_url(raw_url: str) -> str:
    candidate = raw_url.strip()
    if candidate.startswith("demo://"):
        service_id = candidate.removeprefix("demo://")
        if service_id in DEMO_SERVICE_TARGETS and candidate == f"demo://{service_id}":
            return candidate
        raise ValueError("Choose one of the included demo services; custom demo targets are not allowed.")
    return validate_public_url(raw_url).url


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, hostname: str, port: int, address: str) -> None:
        super().__init__(hostname, port, timeout=10.0)
        self.address = address

    def connect(self) -> None:
        self.sock = socket.create_connection((self.address, self.port), self.timeout)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, hostname: str, port: int, address: str) -> None:
        self.ssl_context = ssl.create_default_context()
        super().__init__(hostname, port, timeout=10.0, context=self.ssl_context)
        self.address = address

    def connect(self) -> None:
        raw_socket = socket.create_connection((self.address, self.port), self.timeout)
        try:
            self.sock = self.ssl_context.wrap_socket(raw_socket, server_hostname=self.host)
        except Exception:
            raw_socket.close()
            raise


def check_public_url(raw_url: str) -> dict[str, object]:
    target = validate_public_url(raw_url)
    started = time.perf_counter()
    checked_at = datetime.now(timezone.utc).replace(tzinfo=None)
    response_status: int | None = None
    deadline = started + 10.0

    for address in target.addresses:
        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            break
        connection: http.client.HTTPConnection
        if target.scheme == "https":
            connection = _PinnedHTTPSConnection(target.hostname, target.port, address)
        else:
            connection = _PinnedHTTPConnection(target.hostname, target.port, address)
        connection.timeout = remaining
        try:
            connection.request(
                "GET",
                target.request_target,
                headers={
                    "Host": target.host_header,
                    "User-Agent": "CodePulse-Monitor/1.0",
                    "Connection": "close",
                },
            )
            response_status = connection.getresponse().status
            break
        except (OSError, http.client.HTTPException, ssl.SSLError):
            continue
        finally:
            connection.close()

    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    if response_status is None:
        result = "unavailable"
        reachable = False
        message = "The website could not be reached within the 10-second timeout."
    elif 200 <= response_status < 300:
        result = "healthy"
        reachable = True
        message = "The website responded successfully."
    elif 300 <= response_status < 400:
        result = "redirect"
        reachable = True
        message = "The website responded with a redirect. Redirect target was not followed."
    elif response_status < 500:
        result = "client_error"
        reachable = True
        message = "The website is reachable but returned an HTTP client error."
    else:
        result = "server_error"
        reachable = True
        message = "The website is reachable but returned an HTTP server error."

    return {
        "url": target.url,
        "result": result,
        "reachable": reachable,
        "status_code": response_status,
        "response_time_ms": elapsed_ms,
        "message": message,
        "checked_at": checked_at.isoformat() + "Z",
    }


def check_monitor_url(raw_url: str) -> dict[str, object]:
    if not raw_url.startswith("demo://"):
        return check_public_url(raw_url)

    normalized_url = validate_monitor_url(raw_url)
    service_id = normalized_url.removeprefix("demo://")
    hostname, port = DEMO_SERVICE_TARGETS[service_id]
    try:
        resolved_addresses = {
            ipaddress.ip_address(info[4][0])
            for info in socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
        }
    except (OSError, ValueError) as exc:
        raise ValueError("The selected demo service is unavailable from this backend.") from exc
    if not resolved_addresses or any(
        not address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        for address in resolved_addresses
    ):
        raise ValueError("The selected demo service did not resolve to an allowed private service address.")

    started = time.perf_counter()
    checked_at = datetime.now(timezone.utc).replace(tzinfo=None)
    response_status: int | None = None
    for address in resolved_addresses:
        connection = _PinnedHTTPConnection(hostname, port, str(address))
        connection.timeout = max(0.1, 10.0 - (time.perf_counter() - started))
        try:
            connection.request(
                "GET",
                "/health",
                headers={
                    "Host": f"{hostname}:{port}",
                    "User-Agent": "CodePulse-Monitor/1.0",
                    "Connection": "close",
                },
            )
            response_status = connection.getresponse().status
            break
        except (OSError, http.client.HTTPException):
            continue
        finally:
            connection.close()

    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    if response_status is None:
        result = "unavailable"
        reachable = False
        message = "The selected demo service could not be reached within the 10-second timeout."
    elif 200 <= response_status < 300:
        result = "healthy"
        reachable = True
        message = "The demo service health endpoint responded successfully."
    elif 300 <= response_status < 400:
        result = "redirect"
        reachable = True
        message = "The demo service returned a redirect. Redirect target was not followed."
    elif response_status < 500:
        result = "client_error"
        reachable = True
        message = "The demo service is reachable but returned an HTTP client error."
    else:
        result = "server_error"
        reachable = True
        message = "The demo service is reachable but returned an HTTP server error."

    return {
        "url": normalized_url,
        "result": result,
        "reachable": reachable,
        "status_code": response_status,
        "response_time_ms": elapsed_ms,
        "message": message,
        "checked_at": checked_at.isoformat() + "Z",
    }


def _as_utc_naive(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def run_monitor_check(
    db: Session,
    monitor: Monitor,
    checker=check_monitor_url,
    now: datetime | None = None,
) -> MonitorCheck:
    started = time.perf_counter()
    try:
        result = checker(monitor.url)
    except ValueError as exc:
        result = {
            "result": "unavailable",
            "reachable": False,
            "status_code": None,
            "response_time_ms": round((time.perf_counter() - started) * 1000, 1),
            "message": str(exc),
        }
    except (OSError, TimeoutError, http.client.HTTPException, ssl.SSLError):
        logger.warning("Monitor check failed for monitor_id=%s", monitor.id)
        result = {
            "result": "unavailable",
            "reachable": False,
            "status_code": None,
            "response_time_ms": round((time.perf_counter() - started) * 1000, 1),
            "message": "The website could not be reached. Check the URL and try again.",
        }

    checked_at = _as_utc_naive(now or datetime.now(timezone.utc))
    check = MonitorCheck(
        monitor_id=monitor.id,
        result=str(result["result"]),
        reachable=bool(result["reachable"]),
        status_code=result["status_code"],
        response_time_ms=float(result["response_time_ms"]),
        message=str(result["message"]),
        checked_at=checked_at,
    )
    db.add(check)
    db.flush()
    CHECKS_TOTAL.labels(check.result).inc()
    CHECK_DURATION.observe(max(0.0, check.response_time_ms / 1000))

    failed = check.result != "healthy"
    monitor.consecutive_failures = monitor.consecutive_failures + 1 if failed else 0
    incident = db.scalar(
        select(MonitorIncident)
        .where(MonitorIncident.monitor_id == monitor.id, MonitorIncident.status == "open")
        .order_by(MonitorIncident.created_at.desc())
        .limit(1)
    )

    evidence = {
        "url": monitor.url,
        "result": check.result,
        "status_code": check.status_code,
        "response_time_ms": check.response_time_ms,
        "message": check.message,
        "consecutive_failures": monitor.consecutive_failures,
        "checked_at": check.checked_at.isoformat() + "Z",
    }
    should_open_incident = (
        check.result == "server_error"
        or monitor.consecutive_failures >= 2
        or check.response_time_ms >= 5000
    )
    if should_open_incident:
        if incident is None:
            incident = MonitorIncident(
                monitor_id=monitor.id,
                user_id=monitor.user_id,
                title=f"Health check failed: {monitor.name}",
                severity="high" if check.result in {"server_error", "unavailable"} else "medium",
                evidence=evidence,
            )
            db.add(incident)
            INCIDENTS_CREATED.inc()
        else:
            incident.evidence = evidence
            incident.updated_at = checked_at
    elif not failed and incident is not None:
        incident.status = "resolved"
        incident.resolved_at = checked_at
        incident.updated_at = checked_at
        incident.evidence = {**(incident.evidence or {}), "recovered_at": checked_at.isoformat() + "Z"}

    db.execute(
        delete(MonitorIncident).where(
            MonitorIncident.monitor_id == monitor.id,
            MonitorIncident.status == "resolved",
            MonitorIncident.created_at < checked_at - RESOLVED_INCIDENT_RETENTION,
        )
    )
    old_resolved_ids = db.scalars(
        select(MonitorIncident.id)
        .where(
            MonitorIncident.monitor_id == monitor.id,
            MonitorIncident.status == "resolved",
        )
        .order_by(MonitorIncident.created_at.desc())
        .offset(MAX_RESOLVED_INCIDENTS_PER_MONITOR)
    ).all()
    if old_resolved_ids:
        db.execute(
            delete(MonitorIncident).where(MonitorIncident.id.in_(old_resolved_ids))
        )

    stale_ids = db.scalars(
        select(MonitorCheck.id)
        .where(MonitorCheck.monitor_id == monitor.id)
        .order_by(MonitorCheck.checked_at.desc())
        .offset(MAX_CHECKS_PER_MONITOR)
    ).all()
    if stale_ids:
        db.query(MonitorCheck).filter(MonitorCheck.id.in_(stale_ids)).delete(synchronize_session=False)

    db.commit()
    db.refresh(check)
    return check


def run_due_checks(
    now: datetime | None = None,
    checker=check_monitor_url,
    stop_event: threading.Event | None = None,
) -> int:
    current_time = _as_utc_naive(now or datetime.now(timezone.utc))
    completed = 0
    with SessionLocal() as db:
        due_monitors = db.scalars(
            select(Monitor)
            .where(Monitor.enabled.is_(True), Monitor.next_check_at <= current_time)
            .order_by(Monitor.next_check_at)
            .limit(100)
        ).all()
        for monitor in due_monitors:
            if stop_event is not None and stop_event.is_set():
                break
            run_monitor_check(db, monitor, checker=checker, now=current_time)
            monitor.next_check_at = current_time + timedelta(seconds=monitor.interval_seconds)
            db.commit()
            completed += 1
    return completed
