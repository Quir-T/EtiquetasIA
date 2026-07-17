"""Orchestrates anonymization, NLP extraction, validation and persistence for anamnesis processing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter
from uuid import uuid4
from typing import Any

from src.application.services.labels_catalog_service import LabelsCatalogService
from src.domain.entities.anamnesis_event import AnamnesisEvent, ProcessStatus
from src.domain.exceptions.domain_exceptions import AnonymizationError, PersistenceError, ProviderError, ProviderTimeoutError
from src.domain.interfaces.anonymizer import AnonymizerInterface
from src.domain.interfaces.nlp_provider import NLPProviderInterface
from src.domain.interfaces.repository import AnamnesisRepositoryInterface
from src.shared.exceptions.app_exceptions import AnonymizationValidationError, NLPProviderError, ProcessingTimeoutError, TextTooLongError, TextTooShortError


@dataclass(slots=True)
class AnamnesisService:
    anonymizer: AnonymizerInterface
    nlp_provider: NLPProviderInterface
    repository: AnamnesisRepositoryInterface
    labels_catalog_service: LabelsCatalogService
    max_text_length: int
    nlp_provider_timeout_seconds: int
    prompt_version: str = "v1"

    def _provider_name(self) -> str:
        return type(self.nlp_provider).__name__.removesuffix("NLPProvider").lower() or "nlp"

    def process(
        self,
        patient_id: int,
        doctor_id: int,
        text: str,
        request_source: str | None = None,
    ) -> AnamnesisEvent:
        normalized_text = text.strip()
        process_id = str(uuid4())
        started_at = perf_counter()
        created_at = datetime.now(timezone.utc)
        catalog_version = self.labels_catalog_service.get_catalog_version()

        if not normalized_text:
            failure_event = AnamnesisEvent(
                process_id=process_id,
                patient_id=patient_id,
                doctor_id=doctor_id,
                anonymized_text="",
                prompt_version=self.prompt_version,
                labels_catalog_version=catalog_version,
                provider=self._provider_name(),
                provider_model=None,
                labels_json={"labels": [], "hallazgos": []},
                status=ProcessStatus.VALIDATION_ERROR,
                error_code="TEXT_TOO_SHORT",
                error_message="Text cannot be empty or whitespace only",
                processing_ms=self._elapsed_ms(started_at),
                created_at=created_at,
            )
            self._persist_event(failure_event)
            raise TextTooShortError("Text cannot be empty or whitespace only", process_id=process_id)
        if len(normalized_text) > self.max_text_length:
            failure_event = AnamnesisEvent(
                process_id=process_id,
                patient_id=patient_id,
                doctor_id=doctor_id,
                anonymized_text="",
                prompt_version=self.prompt_version,
                labels_catalog_version=catalog_version,
                provider=self._provider_name(),
                provider_model=None,
                labels_json={"labels": [], "hallazgos": []},
                status=ProcessStatus.VALIDATION_ERROR,
                error_code="TEXT_TOO_LONG",
                error_message="Text exceeds maximum length",
                processing_ms=self._elapsed_ms(started_at),
                created_at=created_at,
            )
            self._persist_event(failure_event)
            raise TextTooLongError(
                "Text exceeds maximum length",
                details={"max_length": self.max_text_length, "provided_length": len(normalized_text)},
                process_id=process_id,
            )

        try:
            anonymized_text = self.anonymizer.anonymize(normalized_text)
        except AnonymizationError as exc:
            failure_event = AnamnesisEvent(
                process_id=process_id,
                patient_id=patient_id,
                doctor_id=doctor_id,
                anonymized_text="",
                prompt_version=self.prompt_version,
                labels_catalog_version=catalog_version,
                provider=self._provider_name(),
                provider_model=None,
                labels_json={"labels": [], "hallazgos": []},
                status=ProcessStatus.VALIDATION_ERROR,
                error_code="ANONYMIZATION_ERROR",
                error_message=str(exc),
                processing_ms=self._elapsed_ms(started_at),
                created_at=created_at,
            )
            self._persist_event(failure_event)
            raise AnonymizationValidationError(str(exc), process_id=process_id) from exc

        allowed_labels = self.labels_catalog_service.get_allowed_labels()

        try:
            provider_result = self.nlp_provider.extract_labels(
                anonymized_text=anonymized_text,
                prompt_version=self.prompt_version,
                allowed_labels=allowed_labels,
                timeout_seconds=self.nlp_provider_timeout_seconds,
            )
        except ProviderTimeoutError as exc:
            self._save_failure_event(
                process_id=process_id,
                patient_id=patient_id,
                doctor_id=doctor_id,
                anonymized_text=anonymized_text,
                catalog_version=catalog_version,
                created_at=created_at,
                processing_ms=self._elapsed_ms(started_at),
                error_code="PROVIDER_TIMEOUT",
                error_message=str(exc),
                status=ProcessStatus.TIMEOUT,
            )
            raise ProcessingTimeoutError(str(exc), process_id=process_id) from exc
        except ProviderError as exc:
            self._save_failure_event(
                process_id=process_id,
                patient_id=patient_id,
                doctor_id=doctor_id,
                anonymized_text=anonymized_text,
                catalog_version=catalog_version,
                created_at=created_at,
                processing_ms=self._elapsed_ms(started_at),
                error_code="PROVIDER_ERROR",
                error_message=str(exc),
                status=ProcessStatus.PROVIDER_ERROR,
            )
            raise NLPProviderError(str(exc), process_id=process_id) from exc

        hallazgos = self._normalize_hallazgos(provider_result.get("hallazgos", []))
        filtered_hallazgos = self.labels_catalog_service.validate_and_filter_hallazgos(hallazgos)
        filtered_labels = [{"name": item["etiqueta"], "confidence": None} for item in filtered_hallazgos]

        event = AnamnesisEvent(
            process_id=process_id,
            patient_id=patient_id,
            doctor_id=doctor_id,
            anonymized_text=anonymized_text,
            prompt_version=self.prompt_version,
            labels_catalog_version=catalog_version,
            provider=str(provider_result.get("provider", "google")),
            provider_model=provider_result.get("model"),
            labels_json={
                "labels": filtered_labels,
                "hallazgos": filtered_hallazgos,
                "raw_response": provider_result,
                "request_source": request_source,
            },
            status=ProcessStatus.SUCCESS,
            error_code=None,
            error_message=None,
            processing_ms=self._elapsed_ms(started_at),
            created_at=created_at,
        )
        return self._persist_event(event)

    def anonymize_only(
        self,
        patient_id: int,
        doctor_id: int,
        text: str,
        request_source: str | None = None,
    ) -> AnamnesisEvent:
        normalized_text = text.strip()
        process_id = str(uuid4())
        started_at = perf_counter()
        created_at = datetime.now(timezone.utc)
        catalog_version = self.labels_catalog_service.get_catalog_version()

        if not normalized_text:
            failure_event = AnamnesisEvent(
                process_id=process_id,
                patient_id=patient_id,
                doctor_id=doctor_id,
                anonymized_text="",
                prompt_version=self.prompt_version,
                labels_catalog_version=catalog_version,
                provider="anonymizer",
                provider_model=None,
                labels_json={"labels": [], "hallazgos": []},
                status=ProcessStatus.VALIDATION_ERROR,
                error_code="TEXT_TOO_SHORT",
                error_message="Text cannot be empty or whitespace only",
                processing_ms=self._elapsed_ms(started_at),
                created_at=created_at,
            )
            self._persist_event(failure_event)
            raise TextTooShortError("Text cannot be empty or whitespace only", process_id=process_id)
        if len(normalized_text) > self.max_text_length:
            failure_event = AnamnesisEvent(
                process_id=process_id,
                patient_id=patient_id,
                doctor_id=doctor_id,
                anonymized_text="",
                prompt_version=self.prompt_version,
                labels_catalog_version=catalog_version,
                provider="anonymizer",
                provider_model=None,
                labels_json={"labels": [], "hallazgos": []},
                status=ProcessStatus.VALIDATION_ERROR,
                error_code="TEXT_TOO_LONG",
                error_message="Text exceeds maximum length",
                processing_ms=self._elapsed_ms(started_at),
                created_at=created_at,
            )
            self._persist_event(failure_event)
            raise TextTooLongError(
                "Text exceeds maximum length",
                details={"max_length": self.max_text_length, "provided_length": len(normalized_text)},
                process_id=process_id,
            )

        try:
            anonymized_text = self.anonymizer.anonymize(normalized_text)
        except AnonymizationError as exc:
            failure_event = AnamnesisEvent(
                process_id=process_id,
                patient_id=patient_id,
                doctor_id=doctor_id,
                anonymized_text="",
                prompt_version=self.prompt_version,
                labels_catalog_version=catalog_version,
                provider="anonymizer",
                provider_model=None,
                labels_json={"labels": [], "hallazgos": []},
                status=ProcessStatus.VALIDATION_ERROR,
                error_code="ANONYMIZATION_ERROR",
                error_message=str(exc),
                processing_ms=self._elapsed_ms(started_at),
                created_at=created_at,
            )
            self._persist_event(failure_event)
            raise AnonymizationValidationError(str(exc), process_id=process_id) from exc

        event = AnamnesisEvent(
            process_id=process_id,
            patient_id=patient_id,
            doctor_id=doctor_id,
            anonymized_text=anonymized_text,
            prompt_version=self.prompt_version,
            labels_catalog_version=catalog_version,
            provider="anonymizer",
            provider_model=None,
            labels_json={
                "labels": [{"name": "solo_anonimizado", "confidence": 1.0}],
                "hallazgos": [],
                "request_source": request_source,
                "operation": "anonymize_only",
            },
            status=ProcessStatus.SUCCESS,
            error_code=None,
            error_message=None,
            processing_ms=self._elapsed_ms(started_at),
            created_at=created_at,
        )
        return self._persist_event(event)

    def get_process(self, process_id: str) -> AnamnesisEvent | None:
        return self.repository.get_by_process_id(process_id)

    def _save_failure_event(
        self,
        process_id: str,
        patient_id: int,
        doctor_id: int,
        anonymized_text: str,
        catalog_version: str,
        created_at: datetime,
        processing_ms: int,
        error_code: str,
        error_message: str,
        status: ProcessStatus,
    ) -> AnamnesisEvent:
        event = AnamnesisEvent(
            process_id=process_id,
            patient_id=patient_id,
            doctor_id=doctor_id,
            anonymized_text=anonymized_text,
            prompt_version=self.prompt_version,
            labels_catalog_version=catalog_version,
            provider=self._provider_name(),
            provider_model=None,
            labels_json={"labels": [], "hallazgos": []},
            status=status,
            error_code=error_code,
            error_message=error_message,
            processing_ms=processing_ms,
            created_at=created_at,
        )
        return self._persist_event(event)

    def _persist_event(self, event: AnamnesisEvent) -> AnamnesisEvent:
        try:
            return self.repository.save(event)
        except PersistenceError as exc:
            raise PersistenceError(str(exc)) from exc

    def _normalize_hallazgos(self, hallazgos: list[dict[str, Any]] | Any) -> list[dict[str, Any]]:
        if not isinstance(hallazgos, list):
            return []
        normalized: list[dict[str, Any]] = []
        for hallazgo in hallazgos:
            if not isinstance(hallazgo, dict):
                continue
            normalized.append(
                {
                    "etiqueta": hallazgo.get("etiqueta"),
                    "descripcion": hallazgo.get("descripcion"),
                    "confidence": hallazgo.get("confidence"),
                }
            )
        return normalized

    @staticmethod
    def _elapsed_ms(started_at: float) -> int:
        return int((perf_counter() - started_at) * 1000)
