"""Use case that retrieves a single audit event by process identifier."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.domain.interfaces.repository import AnamnesisRepositoryInterface


@dataclass(slots=True)
class GetAuditEventUseCase:
    repository: AnamnesisRepositoryInterface

    def execute(self, process_id: str) -> dict[str, Any] | None:
        return self.repository.get_audit_event_by_process_id(process_id=process_id)