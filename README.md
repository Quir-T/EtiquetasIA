# Proyecto IA Etiquetas

API REST para anonimización y procesamiento de anamnesis clínicas.

**Estado:** implementado  
**Stack:** FastAPI, PostgreSQL, Alembic, Docker Compose

## Descripción

Este proyecto expone una API para:

- Anonimizar texto clínico de anamnesis.
- Procesar anamnesis con proveedor NLP configurable (Google o Qwen) y extraer hallazgos.
- Persistir datos clínicos y trazabilidad operativa de manera inmutable.

La API está versionada en `/api/v1` y protegida con API Key en `X-API-Key`.
Los endpoints de salud estan en: `/health/live` y `/health`.
La documentación interactiva de OpenAPI queda disponible en `/docs` y `/openapi.json`.

## Funcionalidades

- `POST /api/v1/anamnesis/anonymize`: anonimiza texto sin invocar NLP.
- `POST /api/v1/anamnesis/process`: anonimiza + NLP + filtro por catálogo + persistencia.
- `GET /api/v1/anamnesis/process/{process_id}`: recupera un proceso por ID (datos clínicos).
- `GET /api/v1/catalog/labels`: devuelve catálogo cerrado de etiquetas.
- `GET /api/v1/audit/events`: lista eventos de auditoría (paginado).
- `GET /api/v1/audit/processes/{process_id}`: devuelve último evento de auditoría por `process_id`.
- `GET /health/live`: liveness.
- `GET /health`: readiness (DB + proveedor NLP).

## Arquitectura

Capas principales:

- **API:** routers, schemas, seguridad, handlers de excepciones.
- **Application:** servicios y casos de uso.
- **Domain:** entidades, interfaces y excepciones de dominio.
- **Infrastructure:** repositorio PostgreSQL, proveedor NLP, adapter de anonymizer, loader de catálogo.

Persistencia:

- `anamnesis_processing_events`
- `anamnesis_processing_audit`

Separación de responsabilidades:

- `anamnesis_processing_events`: datos clínicos/funcionales del proceso.
- `anamnesis_processing_audit`: datos operativos de trazabilidad (errores, tiempos, versiones, proveedor).
- Relación: `events` -> `audit` es 1:1 por `process_id` (enforced con `UNIQUE` en `audit.process_id`).

Inmutabilidad:

- Triggers en DB bloquean `UPDATE/DELETE` en ambas tablas.

## Contrato

### POST /api/v1/anamnesis/process

Respuesta 200:

```json
{
  "process_id": "uuid",
  "created_at": "2026-07-16T10:24:31Z",
  "hallazgos": [
    {"etiqueta": "...", "descripcion": "..."}
  ],
  "processing_ms": 3200
}
```

### GET /api/v1/anamnesis/process/{process_id}

Respuesta 200:

```json
{
  "process_id": "uuid",
  "patient_id": 12345,
  "doctor_id": 678,
  "anonymized_text": "Paciente [ANONIMIZADO]...",
  "hallazgos": [
    {"etiqueta": "...", "descripcion": "..."}
  ],
  "status": "success",
  "created_at": "2026-07-16T10:24:31Z"
}
```

Nota:

- `GET /anamnesis/process/{process_id}` ya no expone `error_code`, `error_message` ni `processing_ms`.
- Esos datos operativos están en endpoints de auditoría.

### GET /api/v1/audit/processes/{process_id}

Respuesta 200 (campos principales):

```json
{
  "audit_id": "uuid",
  "process_id": "uuid",
  "action": "process_anamnesis",
  "status": "success",
  "error_code": null,
  "error_message": null,
  "processing_ms": 3200,
  "prompt_version": "v1",
  "labels_catalog_version": "v1",
  "provider": "google",
  "provider_model": "...",
  "metadata_json": {"text_length": 1500},
  "created_at": "2026-07-16T10:24:31Z"
}
```

## Tecnologías

- fastapi==0.115.6
- uvicorn[standard]==0.34.0
- pydantic==2.10.4
- pydantic-settings==2.7.1
- SQLAlchemy==2.0.36
- psycopg[binary]==3.2.4
- alembic==1.14.0
- python-dotenv==1.0.1
- httpx==0.28.1
- spacy==3.8.2

## Requisitos previos

- Docker Engine
- Docker Compose plugin

Verificación:

```bash
docker --version
docker compose version
```

## Arranque rápido con Docker

```bash
cd /ProyectoIA
docker compose up -d --build
docker compose ps
```

Notas:

- API en `http://localhost:8000`
- El entrypoint ejecuta `alembic upgrade head` automáticamente con reintentos.

## Variables de entorno importantes

### Aplicación

- `APP_NAME`
- `LOG_LEVEL`
- `API_KEY`
- `CORS_ORIGINS`
- `MAX_TEXT_LENGTH`
- `NLP_PROVIDER_TIMEOUT_SECONDS`
- `PROMPT_VERSION`

### Base de datos

- `DATABASE_DSN`
- `DB_SSL_MODE`
- `DB_SSL_CA`
- `DB_SSL_CERT`
- `DB_SSL_KEY`

### Anonymizer

- `ANONYMIZER_MODULE`
- `ANONYMIZER_CLASS`

### Proveedor NLP

- `GOOGLE_NLP_ENDPOINT`
- `GOOGLE_NLP_MODEL`
- `GOOGLE_API_KEY`
- `QWEN_NLP_ENDPOINT`
- `QWEN_NLP_MODEL`
- `QWEN_API_KEY`
- `NLP_PROVIDER` (`google` o `qwen`)

### Migraciones en arranque

- `DB_MIGRATION_MAX_RETRIES` (default: 20)
- `DB_MIGRATION_RETRY_DELAY_SECONDS` (default: 3)

## Ejemplos de uso

Define variables:

```bash
export BASE_URL="http://localhost:8000"
export API_KEY="tu_api_key"
```

### Health

```bash
curl -s "$BASE_URL/health/live"
curl -s "$BASE_URL/health"
```

Nota:

- Los endpoints de salud no usan el prefijo `/api/v1` y viven en la raíz del servicio.

### Catálogo

```bash
curl -s -H "X-API-Key: $API_KEY" "$BASE_URL/api/v1/catalog/labels"
```

### Solo anonimizar

```bash
curl -s -X POST "$BASE_URL/api/v1/anamnesis/anonymize" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{
    "patient_id": 12345,
    "doctor_id": 678,
    "text": "Paciente Juan Perez consulta por dolor toracico desde ayer"
  }'
```

### Procesar anamnesis completa

```bash
curl -s -X POST "$BASE_URL/api/v1/anamnesis/process" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{
    "patient_id": 12345,
    "doctor_id": 678,
    "text": "Paciente refiere dolor toracico, tabaquismo activo, alergia a penicilina",
    "request_source": "legacy_php"
  }'
```

### Obtener proceso

```bash
curl -s -H "X-API-Key: $API_KEY" \
  "$BASE_URL/api/v1/anamnesis/process/<process_id>"
```

### Auditoría paginada

```bash
curl -s -H "X-API-Key: $API_KEY" \
  "$BASE_URL/api/v1/audit/events?page=1&page_size=20"
```

### Auditoría por process_id

```bash
curl -s -H "X-API-Key: $API_KEY" \
  "$BASE_URL/api/v1/audit/processes/<process_id>"
```

## Códigos HTTP relevantes

- `200`: OK
- `400`: Error de validación de request
- `401`: API key inválida
- `404`: Recurso no encontrado
- `408`: Timeout de procesamiento/proveedor
- `502`: Error de proveedor NLP
- `503`: Servicio degradado
- `500`: Error interno

## Migraciones y base de datos

Migraciones incluidas:

- `001_initial_schema`

La migración `001_initial_schema` crea:

- tablas `anamnesis_processing_events` y `anamnesis_processing_audit`
- FK `audit.process_id -> events.process_id`
- restricción `UNIQUE` en `audit.process_id` para mantener cardinalidad 1:1
- índices principales en ambas tablas
- triggers de inmutabilidad para bloquear `UPDATE/DELETE`

Ejecutar migraciones manualmente:

```bash
docker compose exec api alembic upgrade head
```

## Operación útil

```bash
docker compose logs -f
docker compose logs -f api
docker compose logs -f postgres
docker compose exec api sh
docker compose exec postgres psql -U app -d anamnesis_db
docker compose restart api
docker compose down
# cuidado: elimina volumenes y DB
docker compose down -v
```

## Troubleshooting rápido

- **API no levanta:** revisar logs de API/Postgres y validar `.env`.
- **Error DB:** revisar `DATABASE_DSN` y health de postgres en `docker compose ps`.
- **401 Unauthorized:** revisar `API_KEY` y header `X-API-Key`.
- **400 en requests:** validar payload (`patient_id`, `doctor_id`, `text`).
- **Fallo NLP:** revisar `GOOGLE_API_KEY`, endpoint y conectividad.

## Estructura del repositorio

- `src/main.py`
- `src/api/`
- `src/application/`
- `src/domain/`
- `src/infrastructure/`
- `migrations/`
- `docker-compose.yml`
- `Dockerfile`
- `alembic.ini`

## Notas

- El contenedor instala `es_core_news_lg` durante build.
- Catálogo cargado desde `src/infrastructure/config/labels_catalog.json`.
- Swagger/OpenAPI: `http://localhost:8000/docs`
