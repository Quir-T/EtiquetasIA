"""Esquemas Pydantic de solicitud para endpoints de procesamiento de anamnesis y anonimizacion."""

from pydantic import BaseModel, Field, field_validator

from src.config.settings import get_settings


def _validate_text_length(value: str) -> str:
    max_text_length = get_settings().max_text_length
    if len(value) > max_text_length:
        raise ValueError(f"text exceeds maximum length of {max_text_length}")
    return value


class ProcessAnamnesisRequest(BaseModel):
    patient_id: int = Field(..., gt=0)
    doctor_id: int = Field(..., gt=0)
    text: str = Field(..., min_length=1)
    request_source: str | None = Field(default=None, max_length=100)

    @field_validator("text")
    @classmethod
    def strip_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("text cannot be empty")
        return _validate_text_length(stripped)


class AnonymizeTextRequest(BaseModel):
    patient_id: int = Field(..., gt=0)
    doctor_id: int = Field(..., gt=0)
    text: str = Field(..., min_length=1)

    @field_validator("text")
    @classmethod
    def strip_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("text cannot be empty")
        return _validate_text_length(stripped)
