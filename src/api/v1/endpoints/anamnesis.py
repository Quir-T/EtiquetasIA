"""Endpoints de anamnesis que anonimizan, procesan y recuperan eventos clinicos."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from src.api.deps import get_anamnesis_service
from src.api.security import require_api_key
from src.api.v1.schemas.request import AnonymizeTextRequest, ProcessAnamnesisRequest
from src.api.v1.schemas.response import AnonymizeTextResponse, GetProcessResponse, HallazgoItem, ProcessAnamnesisResponse
from src.application.services.anamnesis_service import AnamnesisService
from src.domain.exceptions.domain_exceptions import AnonymizationError, PersistenceError, ProviderError, ProviderTimeoutError

router = APIRouter(prefix="/anamnesis")


@router.post("/anonymize", response_model=AnonymizeTextResponse, status_code=status.HTTP_200_OK)
async def anonymize_text(
    payload: AnonymizeTextRequest,
    _: None = Depends(require_api_key),
    service: AnamnesisService = Depends(get_anamnesis_service),
) -> AnonymizeTextResponse:
    try:
        event = service.anonymize_only(
            patient_id=payload.patient_id,
            doctor_id=payload.doctor_id,
            text=payload.text,
            request_source="api_anonymize_only",
        )
    except (AnonymizationError, ProviderTimeoutError, ProviderError, PersistenceError) as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail={"error_code": "INTERNAL_ERROR", "message": str(exc)}) from exc

    return AnonymizeTextResponse(
        process_id=event.process_id,
        patient_id=event.patient_id,
        doctor_id=event.doctor_id,
        anonymized_text=event.anonymized_text,
    )


@router.post("/process", response_model=ProcessAnamnesisResponse, status_code=status.HTTP_200_OK)
async def process_anamnesis(
    payload: ProcessAnamnesisRequest,
    _: None = Depends(require_api_key),
    service: AnamnesisService = Depends(get_anamnesis_service),
) -> ProcessAnamnesisResponse:
    try:
        event = service.process(
            patient_id=payload.patient_id,
            doctor_id=payload.doctor_id,
            text=payload.text,
            request_source=payload.request_source,
        )
    except (AnonymizationError, ProviderTimeoutError, ProviderError, PersistenceError) as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail={"error_code": "INTERNAL_ERROR", "message": str(exc)}) from exc

    hallazgos = [
        HallazgoItem(etiqueta=item["etiqueta"], descripcion=item["descripcion"])
        for item in event.labels_json.get("hallazgos", [])
    ]
    return ProcessAnamnesisResponse(
        process_id=event.process_id,
        created_at=event.created_at,
        hallazgos=hallazgos,
        processing_ms=event.processing_ms,
    )


@router.get("/process/{process_id}", response_model=GetProcessResponse)
async def get_process(
    process_id: str,
    _: None = Depends(require_api_key),
    service: AnamnesisService = Depends(get_anamnesis_service),
) -> GetProcessResponse:
    event = service.get_process(process_id)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"error_code": "PROCESS_NOT_FOUND", "message": f"Process {process_id} not found"})

    hallazgos = [
        HallazgoItem(etiqueta=item["etiqueta"], descripcion=item["descripcion"])
        for item in event.labels_json.get("hallazgos", [])
    ]
    return GetProcessResponse(
        process_id=event.process_id,
        patient_id=event.patient_id,
        doctor_id=event.doctor_id,
        anonymized_text=event.anonymized_text,
        hallazgos=hallazgos,
        status=event.status.value,
        created_at=event.created_at,
    )
