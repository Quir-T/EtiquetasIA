"""Proveedores de dependencias de FastAPI que cachean y ensamblan servicios e infraestructura de la aplicacion."""

from __future__ import annotations

from functools import lru_cache

from src.application.services.anamnesis_service import AnamnesisService
from src.application.services.labels_catalog_service import LabelsCatalogService
from src.config.settings import Settings, get_settings
from src.infrastructure.adapters.anonymizer_adapter import ModuleAnonymizerAdapter
from src.infrastructure.config.labels_catalog_loader import build_default_labels_catalog_loader
from src.infrastructure.persistence.database import DatabaseClient
from src.infrastructure.persistence.postgres_repository import PostgresAnamnesisRepository
from src.domain.interfaces.nlp_provider import NLPProviderInterface
from src.infrastructure.providers.google_nlp_provider import GoogleNLPProvider
from src.infrastructure.providers.qwen_nlp_provider import QwenNLPProvider


@lru_cache

def get_database_client() -> DatabaseClient:
    return DatabaseClient(settings=get_settings())


@lru_cache

def get_anamnesis_repository() -> PostgresAnamnesisRepository:
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
    settings = get_settings()
    if settings.nlp_provider == "qwen":
        return QwenNLPProvider(settings=settings)
    return GoogleNLPProvider(settings=settings)


@lru_cache

def get_anamnesis_service() -> AnamnesisService:
    settings = get_settings()
    return AnamnesisService(
        anonymizer=get_anonymizer(),
        nlp_provider=get_nlp_provider(),
        repository=get_anamnesis_repository(),
        labels_catalog_service=get_labels_catalog_service(),
        max_text_length=settings.max_text_length,
        nlp_provider_timeout_seconds=settings.nlp_provider_timeout_seconds,
        prompt_version=settings.prompt_version,
    )
