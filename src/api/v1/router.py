"""Enrutador versionado de API que agrupa los endpoints de anamnesis, auditoria y catalogo."""

from fastapi import APIRouter

from src.api.v1.endpoints.anamnesis import router as anamnesis_router
from src.api.v1.endpoints.audit import router as audit_router
from src.api.v1.endpoints.catalog import router as catalog_router

router = APIRouter(prefix="/api/v1")

# La agrupación por tags es intencional para que QA pueda localizar con
# rapidez las familias de funcionalidades en la documentación OpenAPI/Swagger.
router.include_router(anamnesis_router, tags=["Anamnesis"])
router.include_router(audit_router, tags=["Audit"])
router.include_router(catalog_router, tags=["Catalog"])
