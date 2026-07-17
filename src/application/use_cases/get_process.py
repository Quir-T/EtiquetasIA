"""Use case that retrieves a persisted anamnesis process by its identifier."""

from src.application.services.anamnesis_service import AnamnesisService
from src.domain.entities.anamnesis_event import AnamnesisEvent


def get_process(service: AnamnesisService, process_id: str) -> AnamnesisEvent | None:
    return service.get_process(process_id)
