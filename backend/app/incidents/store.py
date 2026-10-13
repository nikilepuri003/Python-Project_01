from __future__ import annotations

from typing import Any


class IncidentStore:
    def __init__(self) -> None:
        self._incidents: dict[str, dict[str, Any]] = {}

    def add(self, incident: dict[str, Any]) -> dict[str, Any]:
        self._incidents[incident["id"]] = incident
        return incident

    def list(self) -> list[dict[str, Any]]:
        return list(self._incidents.values())

    def get(self, incident_id: str) -> dict[str, Any] | None:
        return self._incidents.get(incident_id)

    def replace(self, incidents: list[dict[str, Any]]) -> list[dict[str, Any]]:
        self._incidents = {incident["id"]: incident for incident in incidents}
        return self.list()
