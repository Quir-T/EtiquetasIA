"""Port for persisting anamnesis events and reading their audit records."""

from abc import ABC, abstractmethod
from typing import Any, Optional

from src.domain.entities.anamnesis_event import AnamnesisEvent


class AnamnesisRepositoryInterface(ABC):
    """Contrato de persistencia para eventos de anamnesis y auditoría."""

    @abstractmethod
    def save(self, event: AnamnesisEvent) -> AnamnesisEvent:
        """Guarda un evento y su registro de auditoría asociado."""
        raise NotImplementedError

    @abstractmethod
    def get_by_process_id(self, process_id: str) -> Optional[AnamnesisEvent]:
        """Recupera un evento por su identificador de proceso si existe."""
        raise NotImplementedError

    @abstractmethod
    def list_audit_events(self, page: int, page_size: int) -> tuple[list[dict[str, Any]], int]:
        """Devuelve una página de auditoría junto con el total de registros."""
        raise NotImplementedError

    @abstractmethod
    def get_audit_event_by_process_id(self, process_id: str) -> dict[str, Any] | None:
        """Busca el registro de auditoría asociado a un proceso concreto."""
        raise NotImplementedError
