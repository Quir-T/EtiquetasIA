"""Guardia de clave API que protege rutas protegidas mediante el encabezado X-API-Key."""

from fastapi import Depends, Header

from src.config.settings import Settings, get_settings
from src.shared.exceptions.app_exceptions import InvalidAPIKeyError


async def require_api_key(
    x_api_key: str = Header(..., alias="X-API-Key"),
    settings: Settings = Depends(get_settings),
) -> None:
    if x_api_key != settings.api_key:
        raise InvalidAPIKeyError("Invalid API key")
