"""FastAPI application entrypoint that wires settings, logging, routers and global error handlers."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
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
    """Gestiona los hooks de inicio y cierre de la aplicación.

    En este momento no hay tareas de arranque, pero mantener este hook
    explícito ayuda a testers y mantenedores a identificar dónde agregar
    efectos laterales de ciclo de vida en futuras iteraciones.
    """
    yield


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description="API for anonymized anamnesis processing",
    lifespan=lifespan,
)

# La configuración de CORS se toma desde settings para mantener la política
# específica del despliegue fuera de los módulos de endpoints.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Los handlers globales normalizan los payloads de error para que las
# respuestas de la API sean predecibles ante fallos de framework, validación
# y dominio.
app.add_exception_handler(AppException, app_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(Exception, generic_exception_handler)

# Las rutas de negocio versionadas y la ruta de health se montan por
# separado porque atienden a públicos operativos distintos.
app.include_router(v1_router)
app.include_router(health_router)

# Panel de pruebas estático para personal no tecnico. No es un cliente
# privilegiado: usa la misma API Key y los mismos endpoints publicos que
# cualquier otro consumidor (ver src/static/ui/index.html).
app.mount("/ui", StaticFiles(directory="src/static/ui", html=True), name="ui")