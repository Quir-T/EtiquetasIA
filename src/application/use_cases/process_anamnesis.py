"""Use case that runs the full anamnesis processing pipeline."""

from __future__ import annotations

from dataclasses import dataclass

from src.application.services.anamnesis_service import AnamnesisService
from src.application.services.labels_catalog_service import LabelsCatalogService
from src.application.use_cases._common import build_execution_context, persist_failure_event, validate_text_or_raise
from src.domain.entities.anamnesis_event import AnamnesisEvent
from src.domain.entities.anamnesis_event import ProcessStatus
from src.domain.exceptions.domain_exceptions import AnonymizationError, ProviderError, ProviderTimeoutError
from src.domain.interfaces.anonymizer import AnonymizerInterface
from src.domain.interfaces.nlp_provider import NLPProviderInterface
from src.shared.exceptions.app_exceptions import AnonymizationValidationError, NLPProviderError, ProcessingTimeoutError


@dataclass(slots=True)
class ProcessAnamnesisUseCase:
    """Orquesta el flujo completo de procesamiento de una anamnesis."""
    anonymizer: AnonymizerInterface
    nlp_provider: NLPProviderInterface
    application_service: AnamnesisService
    labels_catalog_service: LabelsCatalogService
    max_text_length: int
    nlp_provider_timeout_seconds: int
    prompt_version: str = "v1"

    def execute(
        self,
        patient_id: int,
        doctor_id: int,
        text: str,
    ) -> AnamnesisEvent:
        """Procesa un texto clínico completo: validación, anonimización, extracción y persistencia."""
        context = build_execution_context(text, self.labels_catalog_service)
        provider_name = self._provider_name()
        normalized_text = validate_text_or_raise(
            context,
            application_service=self.application_service,
            patient_id=patient_id,
            doctor_id=doctor_id,
            provider=provider_name,
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
                provider=provider_name,
                processing_ms=self.application_service.elapsed_ms(context.started_at),
                created_at=context.created_at,
                error_code=AnonymizationValidationError.error_code,
                error_message=str(exc),
                status=ProcessStatus.VALIDATION_ERROR,
            )
            raise AnonymizationValidationError(str(exc), process_id=context.process_id) from exc

        allowed_labels = self.labels_catalog_service.get_allowed_labels()

        try:
            provider_result = self.nlp_provider.extract_labels(
                anonymized_text=anonymized_text,
                prompt_version=self.prompt_version,
                allowed_labels=allowed_labels,
                timeout_seconds=self.nlp_provider_timeout_seconds,
            )
        except ProviderTimeoutError as exc:
            persist_failure_event(
                self.application_service,
                process_id=context.process_id,
                patient_id=patient_id,
                doctor_id=doctor_id,
                anonymized_text=anonymized_text,
                prompt_version=self.prompt_version,
                catalog_version=context.catalog_version,
                provider=provider_name,
                processing_ms=self.application_service.elapsed_ms(context.started_at),
                created_at=context.created_at,
                error_code=ProcessingTimeoutError.error_code,
                error_message=str(exc),
                status=ProcessStatus.TIMEOUT,
            )
            raise ProcessingTimeoutError(str(exc), process_id=context.process_id) from exc
        except ProviderError as exc:
            persist_failure_event(
                self.application_service,
                process_id=context.process_id,
                patient_id=patient_id,
                doctor_id=doctor_id,
                anonymized_text=anonymized_text,
                prompt_version=self.prompt_version,
                catalog_version=context.catalog_version,
                provider=provider_name,
                processing_ms=self.application_service.elapsed_ms(context.started_at),
                created_at=context.created_at,
                error_code=NLPProviderError.error_code,
                error_message=str(exc),
                status=ProcessStatus.PROVIDER_ERROR,
            )
            raise NLPProviderError(str(exc), process_id=context.process_id) from exc

        hallazgos = self.application_service.normalize_hallazgos(provider_result.get("hallazgos", []))
        filtered_hallazgos = self.labels_catalog_service.validate_and_filter_hallazgos(hallazgos)

        event = AnamnesisEvent(
            process_id=context.process_id,
            patient_id=patient_id,
            doctor_id=doctor_id,
            anonymized_text=anonymized_text,
            prompt_version=self.prompt_version,
            labels_catalog_version=context.catalog_version,
            provider=provider_name,
            provider_model=provider_result.get("model"),
            labels_json={
                "hallazgos": filtered_hallazgos,
                "raw_response": provider_result,
            },
            status=ProcessStatus.SUCCESS,
            error_code=None,
            error_message=None,
            processing_ms=self.application_service.elapsed_ms(context.started_at),
            created_at=context.created_at,
        )
        return self.application_service.persist_event(event)

    def _provider_name(self) -> str:
        """Devuelve el nombre del provider para trazas y persistencia de eventos."""
        return type(self.nlp_provider).__name__.removesuffix("NLPProvider").lower() or "nlp"
