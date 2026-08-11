"""Endpoints de auditoria que exponen historial de procesamiento inmutable con paginacion y busqueda por id de proceso."""

from __future__ import annotations

import math

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.api.deps import get_get_audit_event_use_case, get_list_audit_events_use_case
from src.api.security import require_api_key
from src.api.v1.schemas.response import AuditEventItem, AuditEventsPageResponse, ErrorResponse
from src.application.use_cases.get_audit_event import GetAuditEventUseCase
from src.application.use_cases.list_audit_events import ListAuditEventsUseCase

router = APIRouter(prefix="/audit")


@router.get("/events", response_model=AuditEventsPageResponse, responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}})
async def get_audit_events(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _: None = Depends(require_api_key),
    use_case: ListAuditEventsUseCase = Depends(get_list_audit_events_use_case),
) -> AuditEventsPageResponse:
    """Lista registros de auditoría con límites de paginación validados.

    Comportamiento relevante para QA:
    - page y page_size están acotados a nivel de validación de request.
    - las páginas fuera de rango devuelven un HTTP 400 estructurado.
    """
    items, total = use_case.execute(page=page, page_size=page_size)
    total_pages = math.ceil(total / page_size) if total > 0 else 0
    if (total == 0 and page > 1) or (total > 0 and page > total_pages):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorResponse(
                error_code="AUDIT_PAGE_OUT_OF_RANGE",
                message=f"Page {page} is out of range for audit events",
                details={"page": page, "page_size": page_size, "total_pages": total_pages, "total": total},
            ).model_dump(exclude_none=False),
        )
    return AuditEventsPageResponse(
        items=items,
        page=page,
        page_size=page_size,
        total=total,
        total_pages=total_pages,
        has_next=page < total_pages,
        has_prev=page > 1,
    )


@router.get("/processes/{process_id}", response_model=AuditEventItem, responses={404: {"model": ErrorResponse}})
async def get_audit_event_by_process_id(
    process_id: str,
    _: None = Depends(require_api_key),
    use_case: GetAuditEventUseCase = Depends(get_get_audit_event_use_case),
) -> AuditEventItem:
    """Devuelve un registro de auditoría asociado a un identificador de proceso.

    Si no existe registro, este endpoint emite un payload HTTP 404 tipado con
    AUDIT_NOT_FOUND para aserciones de prueba deterministas.
    """
    item = use_case.execute(process_id=process_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorResponse(
                error_code="AUDIT_NOT_FOUND",
                message=f"Audit record for process {process_id} not found",
                process_id=process_id,
            ).model_dump(exclude_none=False),
        )
    return AuditEventItem(**item)
