"""Use case that lists paginated audit events."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.domain.interfaces.repository import AnamnesisRepositoryInterface


@dataclass(slots=True)
class ListAuditEventsUseCase:
    repository: AnamnesisRepositoryInterface

    def execute(self, page: int, page_size: int) -> tuple[list[dict[str, Any]], int]:
        return self.repository.list_audit_events(page=page, page_size=page_size)