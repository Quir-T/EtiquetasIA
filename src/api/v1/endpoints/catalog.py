"""Endpoint de catalogo que expone el conjunto cerrado de etiquetas clinicas permitidas."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from src.api.deps import get_labels_catalog_service
from src.api.security import require_api_key
from src.api.v1.schemas.response import CatalogLabelItem, CatalogResponse
from src.application.services.labels_catalog_service import LabelsCatalogService

router = APIRouter(prefix="/catalog")


@router.get("/labels", response_model=CatalogResponse)
async def get_labels_catalog(
    _: None = Depends(require_api_key),
    service: LabelsCatalogService = Depends(get_labels_catalog_service),
) -> CatalogResponse:
    catalog = service.get_catalog()
    raw_last_updated = catalog.get("last_updated")
    last_updated = datetime.fromisoformat(str(raw_last_updated).replace("Z", "+00:00")) if raw_last_updated else datetime.now(timezone.utc)
    return CatalogResponse(
        version=str(catalog.get("version", "unknown")),
        labels=[CatalogLabelItem(name=item["name"], description=item.get("description", "")) for item in catalog.get("labels", [])],
        last_updated=last_updated,
    )
