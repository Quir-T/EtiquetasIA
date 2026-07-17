"""Immutable domain entity that captures the result of an anamnesis processing attempt."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class ProcessStatus(StrEnum):
    SUCCESS = "success"
    PROVIDER_ERROR = "provider_error"
    VALIDATION_ERROR = "validation_error"
    TIMEOUT = "timeout"


@dataclass(frozen=True, slots=True)
class AnamnesisEvent:
    process_id: str
    patient_id: int
    doctor_id: int
    anonymized_text: str
    prompt_version: str
    labels_catalog_version: str
    provider: str
    provider_model: str | None
    labels_json: dict[str, Any]
    status: ProcessStatus
    error_code: str | None
    error_message: str | None
    processing_ms: int
    created_at: datetime
