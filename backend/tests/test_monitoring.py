from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session, sessionmaker

from app.core.auth_sessions import create_user_session, get_or_create_user
from app.core.database import Base, get_db
from app.models.monitoring import Monitor, MonitorCheck, MonitorIncident
from app.services import monitoring
from app.services.monitoring import run_monitor_check, validate_public_url


def make_database() -> tuple[object, sessionmaker[Session]]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def make_user(db: Session, sub: str, email: str):
    user, _ = get_or_create_user(db, {"sub": sub, "email": email, "name": email})
    return user


def test_url_validation_rejects_private_addresses_and_unsafe_ports(monkeypatch) -> None:
    with pytest.raises(ValueError, match="publicly accessible"):
        validate_public_url("http://127.0.0.1")
    with pytest.raises(ValueError, match="port 80 or 443"):
        validate_public_url("https://example.com:8443")

    monkeypatch.setattr(
        monitoring.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (2, 1, 6, "", ("8.8.8.8", 443)),
            (2, 1, 6, "", ("10.0.0.2", 443)),
        ],
    )
    with pytest.raises(ValueError, match="publicly accessible"):
        validate_public_url("https://example.test")


@pytest.mark.parametrize(
    ("status_code", "expected_result"),
    [(200, "healthy"), (302, "redirect"), (503, "server_error")],
)
def test_http_check_classifies_status_and_connects_to_validated_ip(
    monkeypatch,
    status_code: int,
    expected_result: str,
) -> None:
    monkeypatch.setattr(
        monitoring.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("93.184.216.34", 80))],
    )
    requests: list[tuple[str, str, str]] = []

    class FakeConnection:
        def __init__(self, hostname: str, port: int, address: str) -> None:
            assert hostname == "example.test"
            assert port == 80
            assert address == "93.184.216.34"

        def request(self, method: str, target: str, headers: dict[str, str]) -> None:
            requests.append((method, target, headers["Host"]))

        def getresponse(self):
            return SimpleNamespace(status=status_code)

        def close(self) -> None:
            pass

    monkeypatch.setattr(monitoring, "_PinnedHTTPConnection", FakeConnection)
    result = monitoring.check_public_url("http://example.test/status")

    assert result["result"] == expected_result
    assert result["status_code"] == status_code
    assert requests == [("GET", "/status", "example.test")]


def test_http_timeout_is_reported_as_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(
        monitoring.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("93.184.216.34", 80))],
    )
    monkeypatch.setattr(
        monitoring.socket,
        "create_connection",
        lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError()),
    )

    result = monitoring.check_public_url("http://example.test")

    assert result["result"] == "unavailable"
    assert result["reachable"] is False
    assert result["status_code"] is None


def test_demo_service_monitor_uses_only_fixed_private_targets(monkeypatch) -> None:
    assert monitoring.validate_monitor_url("demo://payment-service") == "demo://payment-service"
    with pytest.raises(ValueError, match="custom demo targets"):
        monitoring.validate_monitor_url("demo://169.254.169.254/latest/meta-data")

    monkeypatch.setattr(
        monitoring.socket,
        "getaddrinfo",
        lambda hostname, port, **kwargs: [
            (2, 1, 6, "", ("172.20.0.8", port))
        ],
    )

    class FakeConnection:
        def __init__(self, hostname: str, port: int, address: str) -> None:
            assert (hostname, port, address) == ("payment-service", 8003, "172.20.0.8")

        def request(self, method: str, target: str, headers: dict[str, str]) -> None:
            assert (method, target, headers["Host"]) == ("GET", "/health", "payment-service:8003")

        def getresponse(self):
            return SimpleNamespace(status=200)

        def close(self) -> None:
            pass

    monkeypatch.setattr(monitoring, "_PinnedHTTPConnection", FakeConnection)
    result = monitoring.check_monitor_url("demo://payment-service")
    assert result["result"] == "healthy"
    assert result["url"] == "demo://payment-service"


def test_demo_service_monitor_rejects_public_dns_resolution(monkeypatch) -> None:
    monkeypatch.setattr(
        monitoring.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("8.8.8.8", 8003))],
    )
    with pytest.raises(ValueError, match="allowed private service address"):
        monitoring.check_monitor_url("demo://payment-service")


def test_monitor_checks_persist_incidents_and_resolve_after_recovery() -> None:
    engine, session_factory = make_database()
    with session_factory() as db:
        user = make_user(db, "monitor-user", "monitor@example.com")
        monitor = Monitor(user_id=user.id, name="Example", url="https://example.com")
        db.add(monitor)
        db.commit()

        failure = {
            "result": "server_error",
            "reachable": True,
            "status_code": 503,
            "response_time_ms": 120,
            "message": "Server error",
        }
        first_check = run_monitor_check(
            db,
            monitor,
            checker=lambda _url: failure,
            now=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        incident = db.scalar(select(MonitorIncident))
        assert first_check.result == "server_error"
        assert incident is not None
        assert incident.status == "open"
        assert incident.evidence["status_code"] == 503

        healthy = {
            "result": "healthy",
            "reachable": True,
            "status_code": 200,
            "response_time_ms": 90,
            "message": "OK",
        }
        run_monitor_check(
            db,
            monitor,
            checker=lambda _url: healthy,
            now=datetime(2026, 1, 1, 0, 5, tzinfo=timezone.utc),
        )
        db.refresh(incident)
        assert incident.status == "resolved"
        assert incident.evidence["recovered_at"].endswith("Z")
        assert len(db.scalars(select(MonitorCheck)).all()) == 2

    engine.dispose()


def test_scheduler_checks_only_due_monitors_and_saves_next_run(monkeypatch) -> None:
    engine, session_factory = make_database()
    now = datetime(2026, 1, 1)
    with session_factory() as db:
        user = make_user(db, "scheduler-user", "scheduler@example.com")
        due = Monitor(
            user_id=user.id,
            name="Due",
            url="https://due.example",
            interval_seconds=120,
            next_check_at=now - timedelta(seconds=1),
        )
        later = Monitor(
            user_id=user.id,
            name="Later",
            url="https://later.example",
            interval_seconds=120,
            next_check_at=now + timedelta(minutes=1),
        )
        db.add_all([due, later])
        db.commit()
        due_id, later_id = due.id, later.id

    monkeypatch.setattr(monitoring, "SessionLocal", session_factory)
    calls: list[str] = []
    result = monitoring.run_due_checks(
        now=now,
        checker=lambda url: calls.append(url) or {
            "result": "healthy",
            "reachable": True,
            "status_code": 200,
            "response_time_ms": 80,
            "message": "OK",
        },
    )

    assert result == 1
    assert calls == ["https://due.example"]
    with session_factory() as db:
        assert len(db.scalars(select(MonitorCheck)).all()) == 1
        due = db.get(Monitor, due_id)
        later = db.get(Monitor, later_id)
        assert due is not None and due.next_check_at == now + timedelta(seconds=120)
        assert later is not None and later.next_check_at == now + timedelta(minutes=1)

    engine.dispose()


def test_monitor_api_requires_login_and_hides_other_users_data(monkeypatch) -> None:
    from app.api.v1 import routes

    app = FastAPI()
    app.include_router(routes.router)

    engine, session_factory = make_database()
    with session_factory() as db:
        owner = make_user(db, "owner", "owner@example.com")
        other = make_user(db, "other", "other@example.com")
        owner_token = create_user_session(db, owner)
        other_token = create_user_session(db, other)

    monkeypatch.setattr(
        routes,
        "validate_monitor_url",
        lambda url: url,
    )

    def override_db():
        with session_factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        assert client.get("/api/v1/monitors").status_code == 401

        created = client.post(
            "/api/v1/monitors",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"name": "Public site", "url": "https://example.com", "interval_seconds": 300},
        )
        assert created.status_code == 201
        monitor_id = created.json()["id"]

        owner_list = client.get(
            "/api/v1/monitors",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert len(owner_list.json()["items"]) == 1

        other_list = client.get(
            "/api/v1/monitors",
            headers={"Authorization": f"Bearer {other_token}"},
        )
        other_checks = client.get(
            f"/api/v1/monitors/{monitor_id}/checks",
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert other_list.json()["items"] == []
        assert other_checks.status_code == 404

        update = client.patch(
            f"/api/v1/monitors/{monitor_id}",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"enabled": False},
        )
        assert update.status_code == 200
        assert update.json()["enabled"] is False

        deleted = client.delete(
            f"/api/v1/monitors/{monitor_id}",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert deleted.status_code == 204
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()
