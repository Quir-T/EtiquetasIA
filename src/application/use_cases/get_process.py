"""Use case that retrieves a persisted anamnesis process by its identifier."""

from dataclasses import dataclass

from src.application.services.anamnesis_service import AnamnesisService
from src.domain.entities.anamnesis_event import AnamnesisEvent


@dataclass(slots=True)
class GetProcessUseCase:
    application_service: AnamnesisService

    def execute(self, process_id: str) -> AnamnesisEvent | None:
        return self.application_service.get_process(process_id)
