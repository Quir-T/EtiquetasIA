"""Port for persisting anamnesis events and reading their audit records."""

from abc import ABC, abstractmethod
from typing import Any, Optional

from src.domain.entities.anamnesis_event import AnamnesisEvent


class AnamnesisRepositoryInterface(ABC):
    @abstractmethod
    def save(self, event: AnamnesisEvent) -> AnamnesisEvent:
        raise NotImplementedError

    @abstractmethod
    def get_by_process_id(self, process_id: str) -> Optional[AnamnesisEvent]:
        raise NotImplementedError

    @abstractmethod
    def list_audit_events(self, page: int, page_size: int) -> tuple[list[dict[str, Any]], int]:
        raise NotImplementedError

    @abstractmethod
    def get_audit_event_by_process_id(self, process_id: str) -> dict[str, Any] | None:
        raise NotImplementedError
