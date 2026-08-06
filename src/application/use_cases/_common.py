"""Shared helpers for anamnesis application use cases."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter
from typing import Any
from uuid import uuid4

from src.application.services.anamnesis_service import AnamnesisService
from src.application.services.labels_catalog_service import LabelsCatalogService
from src.domain.entities.anamnesis_event import AnamnesisEvent, ProcessStatus
from src.shared.exceptions.app_exceptions import TextTooLongError, TextTooShortError


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    process_id: str
    normalized_text: str
    started_at: float
    created_at: datetime
    catalog_version: str


def sanitize_input_text(text: str) -> str:
    sanitized = re.sub(r"[\r\n\t\f\v]+", " ", text)
    sanitized = re.sub(r"[\x00-\x1F\x7F]+", " ", sanitized)
    return " ".join(sanitized.split())


def build_execution_context(text: str, labels_catalog_service: LabelsCatalogService) -> ExecutionContext:
    return ExecutionContext(
        process_id=str(uuid4()),
        normalized_text=sanitize_input_text(text),
        started_at=perf_counter(),
        created_at=datetime.now(timezone.utc),
        catalog_version=labels_catalog_service.get_catalog_version(),
    )


def persist_failure_event(
    application_service: AnamnesisService,
    *,
    process_id: str,
    patient_id: int,
    doctor_id: int,
    anonymized_text: str,
    prompt_version: str,
    catalog_version: str,
    provider: str,
    processing_ms: int,
    created_at: datetime,
    error_code: str,
    error_message: str,
    status: ProcessStatus,
    labels_json: dict[str, Any] | None = None,
) -> AnamnesisEvent:
    event = AnamnesisEvent(
        process_id=process_id,
        patient_id=patient_id,
        doctor_id=doctor_id,
        anonymized_text=anonymized_text,
        prompt_version=prompt_version,
        labels_catalog_version=catalog_version,
        provider=provider,
        provider_model=None,
        labels_json=labels_json or {"hallazgos": []},
        status=status,
        error_code=error_code,
        error_message=error_message,
        processing_ms=processing_ms,
        created_at=created_at,
    )
    return application_service.persist_event(event)


def validate_text_or_raise(
    context: ExecutionContext,
    *,
    application_service: AnamnesisService,
    patient_id: int,
    doctor_id: int,
    provider: str,
    max_text_length: int,
    prompt_version: str,
) -> str:
    if not context.normalized_text:
        persist_failure_event(
            application_service,
            process_id=context.process_id,
            patient_id=patient_id,
            doctor_id=doctor_id,
            anonymized_text="",
            prompt_version=prompt_version,
            catalog_version=context.catalog_version,
            provider=provider,
            processing_ms=application_service.elapsed_ms(context.started_at),
            created_at=context.created_at,
            error_code=TextTooShortError.error_code,
            error_message="Text cannot be empty or whitespace only",
            status=ProcessStatus.VALIDATION_ERROR,
        )
        raise TextTooShortError("Text cannot be empty or whitespace only", process_id=context.process_id)

    if len(context.normalized_text) > max_text_length:
        persist_failure_event(
            application_service,
            process_id=context.process_id,
            patient_id=patient_id,
            doctor_id=doctor_id,
            anonymized_text="",
            prompt_version=prompt_version,
            catalog_version=context.catalog_version,
            provider=provider,
            processing_ms=application_service.elapsed_ms(context.started_at),
            created_at=context.created_at,
            error_code=TextTooLongError.error_code,
            error_message="Text exceeds maximum length",
            status=ProcessStatus.VALIDATION_ERROR,
        )
        raise TextTooLongError(
            "Text exceeds maximum length",
            details={"max_length": max_text_length, "provided_length": len(context.normalized_text)},
            process_id=context.process_id,
        )

    return context.normalized_text