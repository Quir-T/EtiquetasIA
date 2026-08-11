"""Use case that anonymizes text and persists the resulting event."""

from __future__ import annotations

from dataclasses import dataclass

from src.application.services.anamnesis_service import AnamnesisService
from src.application.services.labels_catalog_service import LabelsCatalogService
from src.application.use_cases._common import build_execution_context, persist_failure_event, validate_text_or_raise
from src.domain.entities.anamnesis_event import AnamnesisEvent, ProcessStatus
from src.domain.exceptions.domain_exceptions import AnonymizationError
from src.domain.interfaces.anonymizer import AnonymizerInterface
from src.shared.exceptions.app_exceptions import AnonymizationValidationError


@dataclass(slots=True)
class AnonymizeTextUseCase:
    anonymizer: AnonymizerInterface
    application_service: AnamnesisService
    labels_catalog_service: LabelsCatalogService
    max_text_length: int
    prompt_version: str = "v1"

    def execute(
        self,
        patient_id: int,
        doctor_id: int,
        text: str,
    ) -> AnamnesisEvent:
        context = build_execution_context(text, self.labels_catalog_service)
        normalized_text = validate_text_or_raise(
            context,
            application_service=self.application_service,
            patient_id=patient_id,
            doctor_id=doctor_id,
            provider="anonymizer",
            max_text_length=self.max_text_length,
            prompt_version=self.prompt_version,
        )

        try:
            anonymized_text = self.anonymizer.anonymize(normalized_text)
        except AnonymizationError as exc:
            persist_failure_event(
                self.application_service,
                process_id=context.process_id,
                patient_id=patient_id,
                doctor_id=doctor_id,
                anonymized_text="",
                prompt_version=self.prompt_version,
                catalog_version=context.catalog_version,
                provider="anonymizer",
                processing_ms=self.application_service.elapsed_ms(context.started_at),
                created_at=context.created_at,
                error_code=AnonymizationValidationError.error_code,
                error_message=str(exc),
                status=ProcessStatus.VALIDATION_ERROR,
            )
            raise AnonymizationValidationError(str(exc), process_id=context.process_id) from exc

        event = AnamnesisEvent(
            process_id=context.process_id,
            patient_id=patient_id,
            doctor_id=doctor_id,
            anonymized_text=anonymized_text,
            prompt_version=self.prompt_version,
            labels_catalog_version=context.catalog_version,
            provider="anonymizer",
            provider_model=None,
            labels_json={
                "hallazgos": [],
                "operation": "anonymize_only",
            },
            status=ProcessStatus.SUCCESS,
            error_code=None,
            error_message=None,
            processing_ms=self.application_service.elapsed_ms(context.started_at),
            created_at=context.created_at,
        )
        return self.application_service.persist_event(event)