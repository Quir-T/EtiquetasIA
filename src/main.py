"""FastAPI application entrypoint that wires settings, logging, routers and global error handlers."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.api.exception_handlers import app_exception_handler, generic_exception_handler, http_exception_handler, validation_exception_handler
from src.api.v1.endpoints.health import router as health_router
from src.api.v1.router import router as v1_router
from src.config.settings import get_settings
from src.shared.exceptions.app_exceptions import AppException
from src.shared.logging.logger import setup_logging

settings = get_settings()
setup_logging(settings.log_level)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description="API for anonymized anamnesis processing",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_exception_handler(AppException, app_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(Exception, generic_exception_handler)

app.include_router(v1_router)
app.include_router(health_router)
