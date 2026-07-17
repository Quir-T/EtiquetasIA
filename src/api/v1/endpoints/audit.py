"""Endpoints de auditoria que exponen historial de procesamiento inmutable con paginacion y busqueda por id de proceso."""

from __future__ import annotations

import math

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.api.deps import get_anamnesis_repository
from src.api.security import require_api_key
from src.api.v1.schemas.response import AuditEventItem, AuditEventsPageResponse
from src.infrastructure.persistence.postgres_repository import PostgresAnamnesisRepository

router = APIRouter(prefix="/audit")


@router.get("/events", response_model=AuditEventsPageResponse)
async def get_audit_events(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _: None = Depends(require_api_key),
    repository: PostgresAnamnesisRepository = Depends(get_anamnesis_repository),
) -> AuditEventsPageResponse:
    items, total = repository.list_audit_events(page=page, page_size=page_size)
    total_pages = math.ceil(total / page_size) if total > 0 else 0
    return AuditEventsPageResponse(
        items=items,
        page=page,
        page_size=page_size,
        total=total,
        total_pages=total_pages,
        has_next=page < total_pages,
        has_prev=page > 1,
    )


@router.get("/processes/{process_id}", response_model=AuditEventItem)
async def get_audit_event_by_process_id(
    process_id: str,
    _: None = Depends(require_api_key),
    repository: PostgresAnamnesisRepository = Depends(get_anamnesis_repository),
) -> AuditEventItem:
    item = repository.get_audit_event_by_process_id(process_id=process_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "AUDIT_NOT_FOUND",
                "message": f"Audit record for process {process_id} not found",
            },
        )
    return AuditEventItem(**item)
