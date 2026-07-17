"""Esquemas Pydantic de respuesta que definen las cargas de la API publica para procesos, auditoria, catalogo y salud."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class HallazgoItem(BaseModel):
    etiqueta: str
    descripcion: str


class ProcessAnamnesisResponse(BaseModel):
    process_id: str
    created_at: datetime
    hallazgos: list[HallazgoItem]
    processing_ms: int


class AnonymizeTextResponse(BaseModel):
    process_id: str
    patient_id: int
    doctor_id: int
    anonymized_text: str


class GetProcessResponse(BaseModel):
    process_id: str
    patient_id: int
    doctor_id: int
    anonymized_text: str
    hallazgos: list[HallazgoItem]
    status: str
    created_at: datetime


class ErrorResponse(BaseModel):
    error_code: str
    message: str
    details: dict | None = None
    process_id: str | None = None


class HealthResponse(BaseModel):
    status: str
    database: str
    nlp_provider: str
    timestamp: datetime


class CatalogLabelItem(BaseModel):
    name: str
    description: str


class CatalogResponse(BaseModel):
    version: str
    labels: list[CatalogLabelItem]
    last_updated: datetime


class AuditEventItem(BaseModel):
    audit_id: str
    process_id: str
    action: str
    status: str
    error_code: str | None = None
    error_message: str | None = None
    processing_ms: int
    prompt_version: str
    labels_catalog_version: str
    provider: str
    provider_model: str | None = None
    metadata_json: dict[str, Any]
    created_at: datetime


class AuditEventsPageResponse(BaseModel):
    items: list[AuditEventItem]
    page: int
    page_size: int
    total: int
    total_pages: int
    has_next: bool
    has_prev: bool
