"""Use case that runs the full anamnesis processing pipeline."""

from src.application.services.anamnesis_service import AnamnesisService
from src.domain.entities.anamnesis_event import AnamnesisEvent


def process_anamnesis(
    service: AnamnesisService,
    patient_id: int,
    doctor_id: int,
    text: str,
    request_source: str | None = None,
) -> AnamnesisEvent:
    return service.process(
        patient_id=patient_id,
        doctor_id=doctor_id,
        text=text,
        request_source=request_source,
    )
