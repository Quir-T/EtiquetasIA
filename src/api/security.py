"""Guardias de clave API para lectura y escritura mediante el encabezado X-API-Key."""

from fastapi import Depends, Header

from src.config.settings import Settings, get_settings
from src.shared.exceptions.app_exceptions import InvalidAPIKeyError


async def require_api_key_write(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    settings: Settings = Depends(get_settings),
) -> None:
    if x_api_key != settings.api_key_write:
        raise InvalidAPIKeyError("Invalid API key for write access")

async def require_api_key_read(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    settings: Settings = Depends(get_settings),
) -> None:
    if x_api_key != settings.api_key_read:
        raise InvalidAPIKeyError("Invalid API key for read access")
