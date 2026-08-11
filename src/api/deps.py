"""Proveedores de dependencias de FastAPI que cachean y ensamblan casos de uso e infraestructura."""

from __future__ import annotations

from functools import lru_cache

from src.application.services.anamnesis_service import AnamnesisService
from src.application.services.labels_catalog_service import LabelsCatalogService
from src.application.use_cases.get_audit_event import GetAuditEventUseCase
from src.application.use_cases.anonymize_text import AnonymizeTextUseCase
from src.application.use_cases.list_audit_events import ListAuditEventsUseCase
from src.application.use_cases.get_process import GetProcessUseCase
from src.application.use_cases.process_anamnesis import ProcessAnamnesisUseCase
from src.config.settings import get_settings
from src.infrastructure.adapters.anonymizer_adapter import ModuleAnonymizerAdapter
from src.infrastructure.config.labels_catalog_loader import build_default_labels_catalog_loader
from src.infrastructure.persistence.database import DatabaseClient
from src.infrastructure.persistence.postgres_repository import PostgresAnamnesisRepository
from src.domain.interfaces.nlp_provider import NLPProviderInterface
from src.infrastructure.providers.google_nlp_provider import GoogleNLPProvider
from src.infrastructure.providers.qwen_nlp_provider import QwenNLPProvider


@lru_cache

def get_database_client() -> DatabaseClient:
    """Crea un cliente de base de datos reutilizable por toda la app."""
    return DatabaseClient(settings=get_settings())


@lru_cache

def get_anamnesis_repository() -> PostgresAnamnesisRepository:
    """Ensambla el repositorio persistente usado por casos de uso y servicios."""
    database_client = get_database_client()
    engine = database_client.create_engine()
    return PostgresAnamnesisRepository(engine=engine)


@lru_cache

def get_labels_catalog_service() -> LabelsCatalogService:
    return LabelsCatalogService(labels_catalog=build_default_labels_catalog_loader())


@lru_cache

def get_anonymizer() -> ModuleAnonymizerAdapter:
    return ModuleAnonymizerAdapter(settings=get_settings())


@lru_cache

def get_nlp_provider() -> NLPProviderInterface:
    """Selecciona el proveedor de NLP activo según la configuración del entorno."""
    settings = get_settings()
    if settings.nlp_provider == "qwen":
        return QwenNLPProvider(settings=settings)
    return GoogleNLPProvider(settings=settings)


@lru_cache

def get_anamnesis_service() -> AnamnesisService:
    return AnamnesisService(repository=get_anamnesis_repository())


@lru_cache

def get_process_anamnesis_use_case() -> ProcessAnamnesisUseCase:
    """Compone el use case principal del flujo de procesamiento de anamnesis."""
    settings = get_settings()
    return ProcessAnamnesisUseCase(
        anonymizer=get_anonymizer(),
        nlp_provider=get_nlp_provider(),
        application_service=get_anamnesis_service(),
        labels_catalog_service=get_labels_catalog_service(),
        max_text_length=settings.max_text_length,
        nlp_provider_timeout_seconds=settings.nlp_provider_timeout_seconds,
        prompt_version=settings.prompt_version,
    )


@lru_cache

def get_anonymize_text_use_case() -> AnonymizeTextUseCase:
    """Compone el use case de anonimización simple para endpoints de texto."""
    settings = get_settings()
    return AnonymizeTextUseCase(
        anonymizer=get_anonymizer(),
        application_service=get_anamnesis_service(),
        labels_catalog_service=get_labels_catalog_service(),
        max_text_length=settings.max_text_length,
        prompt_version=settings.prompt_version,
    )


@lru_cache

def get_get_process_use_case() -> GetProcessUseCase:
    return GetProcessUseCase(application_service=get_anamnesis_service())


@lru_cache

def get_list_audit_events_use_case() -> ListAuditEventsUseCase:
    return ListAuditEventsUseCase(repository=get_anamnesis_repository())


@lru_cache

def get_get_audit_event_use_case() -> GetAuditEventUseCase:
    return GetAuditEventUseCase(repository=get_anamnesis_repository())
