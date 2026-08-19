# Proyecto IA Etiquetas

API REST para anonimización, extracción de hallazgos clínicos y auditoría de anamnesis.

**Estado:** implementado y actualizado al estado actual del repositorio  
**Stack:** FastAPI, PostgreSQL, Alembic, Docker Compose, httpx, anonymizers configurables

## Descripción

El repositorio contiene:

- una API versionada en `/api/v1`;
- persistencia inmutable separada entre datos clínicos y auditoría operacional;
- proveedores NLP configurables entre Google y Qwen/Ollama;
- anonymizers seleccionables por entorno.

La API usa `X-API-Key` para proteger los endpoints funcionales. Los endpoints de salud viven en `/health/live` y `/health`. La documentación OpenAPI está expuesta en `/docs` y `/openapi.json`.

## Funcionalidades

- `POST /api/v1/anamnesis/anonymize`: anonimiza texto sin invocar NLP.
- `POST /api/v1/anamnesis/process`: anonimiza, extrae hallazgos, filtra contra catálogo y persiste.
- `GET /api/v1/anamnesis/process/{process_id}`: devuelve la vista clínica del proceso.
- `GET /api/v1/catalog/labels`: expone el catálogo cerrado de etiquetas.
- `GET /api/v1/audit/events`: lista eventos de auditoría con paginación.
- `GET /api/v1/audit/processes/{process_id}`: recupera la auditoría asociada al proceso.
- `GET /health/live`: liveness.
- `GET /health`: readiness de base de datos y proveedor NLP.

## Arquitectura

Capas principales:

- **API:** routers, seguridad, handlers y dependencias cacheadas.
- **Application:** casos de uso y servicios.
- **Domain:** entidades, puertos y excepciones.
- **Infrastructure:** PostgreSQL, providers NLP, anonymizers y catálogo.

Persistencia:

- `anamnesis_processing_events`: payload clínico y estado funcional.
- `anamnesis_processing_audit`: trazabilidad operativa, errores, tiempos, proveedor y versiones.

La relación `events -> audit` es `1:1` por `process_id`. Ambos lados son append-only y la base bloquea `UPDATE/DELETE` mediante triggers.

## Estado actual de anonymización y NLP

La selección del anonymizer es dinámica mediante `ANONYMIZER_MODULE` y `ANONYMIZER_CLASS`.

Implementaciones presentes en el repositorio:

- `LegacySpacyAnonymizer`
- `PresidioTransformerAnonymizer`

Punto importante:

- `.env.example` sigue apuntando al anonymizer legacy.
- `requirements.txt` ya incluye el stack de Presidio y Transformers, por lo que el repositorio soporta una implementación más pesada aunque no sea la default del ejemplo.

Providers NLP disponibles:

- `google`: llamado HTTP a Google Generative Language API.
- `qwen`: llamado HTTP a Ollama/Qwen.

Detalles vigentes:

- Google envía el API key por header `x-goog-api-key`.
- Google soporta reintentos configurables con backoff exponencial.
- Qwen intenta parsear JSON tanto desde `response` como desde `thinking` o `message.content`.

## Dependencias principales

- `fastapi==0.115.6`
- `uvicorn[standard]==0.34.0`
- `pydantic==2.12.5`
- `pydantic-settings==2.7.1`
- `SQLAlchemy==2.0.36`
- `psycopg[binary]==3.2.4`
- `alembic==1.14.0`
- `python-dotenv==1.0.1`
- `httpx==0.28.1`
- `presidio-analyzer[transformers]==2.2.364`
- `presidio-anonymizer==2.2.364`
- `spacy==3.8.14`
- `spacy-transformers==1.4.0`
- `torch==2.13.0`
- `transformers==4.53.2`

## Requisitos previos

- Docker Engine
- Docker Compose plugin
- Opcional para `NLP_PROVIDER=qwen`: una instancia Ollama accesible desde el entorno configurado

Verificación:

```bash
docker --version
docker compose version
```

## Arranque rápido con Docker

1. Crear `.env` a partir de `.env.example`.
2. Ajustar `API_KEY`, credenciales y provider según el entorno.
3. Levantar servicios.

```bash
cd /home/tom/Hospital/ProyectoIA
cp .env.example .env
docker compose up -d --build
docker compose ps
```

Notas:

- API en `http://localhost:8000`
- `docker-entrypoint.sh` ejecuta `alembic upgrade head` al arrancar el contenedor
- el servicio `api` monta `src/` como volumen de solo lectura

## Variables de entorno relevantes

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

Comportamiento actual:

- el adapter instancia la implementación concreta una sola vez por proceso;
- el wiring general de dependencias en `src/api/deps.py` está cacheado con `@lru_cache`.

### Google NLP

- `NLP_PROVIDER=google`
- `GOOGLE_NLP_ENDPOINT`
- `GOOGLE_NLP_MODEL`
- `GOOGLE_API_KEY`
- `GOOGLE_NLP_MAX_RETRIES`
- `GOOGLE_NLP_BASE_BACKOFF_SECONDS`
- `GOOGLE_NLP_MAX_BACKOFF_SECONDS`

### Qwen NLP

- `NLP_PROVIDER=qwen`
- `QWEN_NLP_ENDPOINT`
- `QWEN_NLP_MODEL`
- `QWEN_API_KEY`

Valor actual del ejemplo:

- `QWEN_NLP_ENDPOINT=http://host.docker.internal:11434/api/generate`

## Contrato resumido

Convenciones:

- la salida canónica de extracción es `{"hallazgos": [...]}`;
- `process_id` identifica la trazabilidad funcional;
- la vista operativa completa se consulta por endpoints de auditoría.

### `POST /api/v1/anamnesis/process`

```json
{
  "process_id": "uuid",
  "created_at": "2026-08-11T10:24:31Z",
  "hallazgos": [
    {"etiqueta": "...", "descripcion": "..."}
  ],
  "processing_ms": 3200
}
```

### `GET /api/v1/anamnesis/process/{process_id}`

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
  "created_at": "2026-08-11T10:24:31Z"
}
```

### `GET /api/v1/audit/processes/{process_id}`

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
  "created_at": "2026-08-11T10:24:31Z"
}
```

## Ejemplos de uso

```bash
export BASE_URL="http://localhost:8000"
export API_KEY="tu_api_key"
```

### Health

```bash
curl -s "$BASE_URL/health/live"
curl -s "$BASE_URL/health"
```

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
    "text": "Paciente refiere dolor toracico, tabaquismo activo, alergia a penicilina"
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

### Auditoría por `process_id`

```bash
curl -s -H "X-API-Key: $API_KEY" \
  "$BASE_URL/api/v1/audit/processes/<process_id>"
```

## Migraciones y base de datos

Migración presente:

- `001_initial_schema`

Incluye:

- tablas `anamnesis_processing_events` y `anamnesis_processing_audit`
- enum `process_status_enum`
- FK `audit.process_id -> events.process_id`
- `UNIQUE` en `audit.process_id`
- índices principales
- triggers de inmutabilidad

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
docker compose down -v
```

## Troubleshooting rápido

- Si la API no levanta, revisar logs de `api` y `postgres` y validar `.env`.
- Si falla DB, revisar `DATABASE_DSN`, `docker compose ps` y el readiness de `/health`.
- Si devuelve `401`, revisar `API_KEY` y el header `X-API-Key`.
- Si falla `qwen`, validar conectividad al endpoint configurado en `QWEN_NLP_ENDPOINT`.
- Si falla `google`, revisar `GOOGLE_API_KEY`, endpoint y parámetros de retry/timeout.

## Estructura del repositorio

- `src/`
- `migrations/`
- `docker-compose.yml`
- `Dockerfile`
- `docker-entrypoint.sh`
- `requirements.txt`
- `.env.example`

## Notas

- La documentación principal describe el estado actual del repositorio, no planes futuros.
- Si cambia el contrato o la configuración efectiva, conviene actualizar `README.md` y `SDD.md` en el mismo cambio.
