"""Endpoints de salud que reportan vivacidad y disponibilidad de la API y sus dependencias."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Response, status

from src.api.deps import get_nlp_provider
from src.config.settings import Settings, get_settings
from src.domain.interfaces.nlp_provider import NLPProviderInterface
from src.infrastructure.persistence.database import DatabaseClient
from src.api.v1.schemas.response import HealthResponse

router = APIRouter()


@router.get("/health/live", response_model=dict[str, str])
async def health_live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health", response_model=HealthResponse)
async def health_ready(
    response: Response,
    settings: Settings = Depends(get_settings),
    nlp_provider: NLPProviderInterface = Depends(get_nlp_provider),
) -> HealthResponse:
    database_client = DatabaseClient(settings=settings)
    database_status = "ok"
    nlp_status = "ok"

    try:
        database_client.health_check()
    except Exception:
        database_status = "error"

    if not nlp_provider.health_check(timeout_seconds=2):
        nlp_status = "error"

    service_status = "healthy" if database_status == "ok" and nlp_status == "ok" else "degraded"
    if service_status == "degraded":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return HealthResponse(
        status=service_status,
        database=database_status,
        nlp_provider=nlp_status,
        timestamp=datetime.now(timezone.utc),
    )
