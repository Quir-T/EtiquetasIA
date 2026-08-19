"""Endpoints de anamnesis que anonimizan, procesan y recuperan eventos clinicos."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from src.api.deps import get_anonymize_text_use_case, get_get_process_use_case, get_process_anamnesis_use_case
from src.api.security import require_api_key_read, require_api_key_write
from src.api.v1.schemas.request import AnonymizeTextRequest, ProcessAnamnesisRequest
from src.api.v1.schemas.response import AnonymizeTextResponse, ErrorResponse, GetProcessResponse, HallazgoItem, ProcessAnamnesisResponse
from src.application.use_cases.anonymize_text import AnonymizeTextUseCase
from src.application.use_cases.get_process import GetProcessUseCase
from src.application.use_cases.process_anamnesis import ProcessAnamnesisUseCase
from src.domain.exceptions.domain_exceptions import PersistenceError
from src.shared.exceptions.app_exceptions import ProcessNotFoundError

router = APIRouter(prefix="/anamnesis")


@router.post(
    "/anonymize",
    response_model=AnonymizeTextResponse,
    status_code=status.HTTP_200_OK,
    responses={
        400: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
async def anonymize_text(
    payload: AnonymizeTextRequest,
    _: None = Depends(require_api_key_write),
    use_case: AnonymizeTextUseCase = Depends(get_anonymize_text_use_case),
) -> AnonymizeTextResponse:
    """Crea texto anonimizado y persiste la traza del proceso.

    Contrato del endpoint para QA:
    - devuelve 200 con process_id y anonymized_text en caso de éxito.
    - mapea los fallos de persistencia del repositorio a HTTP 500.
    """
    try:
        event = use_case.execute(
            patient_id=payload.patient_id,
            doctor_id=payload.doctor_id,
            text=payload.text,
        )
    except PersistenceError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail={"error_code": "INTERNAL_ERROR", "message": str(exc)}) from exc

    return AnonymizeTextResponse(
        process_id=event.process_id,
        patient_id=event.patient_id,
        doctor_id=event.doctor_id,
        anonymized_text=event.anonymized_text,
    )


@router.post(
    "/process",
    response_model=ProcessAnamnesisResponse,
    status_code=status.HTTP_200_OK,
    responses={
        400: {"model": ErrorResponse},
        408: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
    },
)
async def process_anamnesis(
    payload: ProcessAnamnesisRequest,
    _: None = Depends(require_api_key_write),
    use_case: ProcessAnamnesisUseCase = Depends(get_process_anamnesis_use_case),
) -> ProcessAnamnesisResponse:
    """Ejecuta el pipeline completo: anonimización + extracción de etiquetas + persistencia.

    Contrato del endpoint para QA:
    - devuelve hallazgos normalizados a partir de labels_json.hallazgos.
    - mapea los fallos de persistencia del repositorio a HTTP 500.
    """
    try:
        event = use_case.execute(
            patient_id=payload.patient_id,
            doctor_id=payload.doctor_id,
            text=payload.text,
        )
    except PersistenceError as exc:
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


@router.get(
    "/process/{process_id}",
    response_model=GetProcessResponse,
    responses={404: {"model": ErrorResponse}},
)
async def get_process(
    process_id: str,
    _: None = Depends(require_api_key_read),
    use_case: GetProcessUseCase = Depends(get_get_process_use_case),
) -> GetProcessResponse:
    """Recupera un proceso persistido por process_id.

    Levanta un error de dominio de no encontrado cuando el proceso no existe,
    el cual es convertido por los handlers globales en un payload estándar 404.
    """
    event = use_case.execute(process_id)
    if event is None:
        raise ProcessNotFoundError(f"Process {process_id} not found", process_id=process_id)

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
