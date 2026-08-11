================================================================================
              SPECIFICATION DRIVEN DEVELOPMENT (SDD)
     API DE ANONIMIZACION, EXTRACCION Y AUDITORIA DE ANAMNESIS
================================================================================

Fecha: 2026-08-11
Version: 1.3.1
Autor: Tomas Quiroga
Entorno de destino: Local (Docker Compose)
Estado: implementado y actualizado al estado actual del repositorio

================================================================================
1. OBJETIVO Y ALCANCE
================================================================================

1.1 Proposito
Desarrollar una API REST que:
- anonimice texto clinico,
- procese anamnesis contra un proveedor NLP configurable,
- persista resultado clinico y trazabilidad operativa de forma inmutable.

1.2 Alcance definido
- Consumidor principal: sistema PHP interno y clientes tecnicos via HTTP JSON.
- Integracion: HTTP JSON con API Key.
- Volumen objetivo: bajo/medio.
- Entorno documentado: Docker Compose local.
- Alcance del repositorio: API, persistencia, anonymizers configurables y proveedores NLP.

1.3 Fuera de alcance
- UI propia.
- Orquestacion cloud productiva.
- Gestion de usuarios finales.
- Edicion o borrado de eventos historicos.

================================================================================
2. ESTADO ACTUAL DEL PROYECTO
================================================================================

2.1 Implementado en el repositorio
- API FastAPI versionada en /api/v1.
- Endpoints de salud en raiz: /health/live y /health.
- Persistencia PostgreSQL con Alembic.
- Auditoria operacional separada de los datos clinicos.
- Proveedor NLP configurable entre Google y Qwen.
- Carga dinamica de anonymizer por variables de entorno.

2.2 Artefactos operativos presentes
- .env.example: configuracion base reproducible.

================================================================================
3. STACK DEL PROYECTO
================================================================================

3.1 Backend
- FastAPI
- Pydantic v2
- SQLAlchemy 2
- Alembic
- PostgreSQL 15
- httpx

3.2 Anonimizacion
- Adapter dinamico por ANONYMIZER_MODULE + ANONYMIZER_CLASS.
- Implementaciones disponibles en el repositorio:
  - LegacySpacyAnonymizer
  - PresidioTransformerAnonymizer
- El adapter cachea lazy la instancia concreta por proceso para evitar recarga de modelos pesados en cada request.

3.3 NLP
- Google Generative Language API via HTTP.
- Qwen/Ollama via HTTP.

3.4 Dependencias principales actuales (requirements.txt)
- fastapi==0.115.6
- uvicorn[standard]==0.34.0
- pydantic==2.12.5
- pydantic-settings==2.7.1
- SQLAlchemy==2.0.36
- psycopg[binary]==3.2.4
- alembic==1.14.0
- python-dotenv==1.0.1
- httpx==0.28.1
- presidio-analyzer[transformers]==2.2.364
- presidio-anonymizer==2.2.364
- spacy==3.8.14
- spacy-transformers==1.4.0
- torch==2.13.0
- transformers==4.53.2

3.5 Servicios Docker definidos
- api
- postgres

================================================================================
4. ARQUITECTURA LOGICA
================================================================================

Capas:
- API: routers, schemas, seguridad, exception handlers y dependencias cacheadas.
- Application: casos de uso y servicios de aplicacion.
- Domain: entidades, interfaces y excepciones de dominio.
- Infrastructure: repositorio PostgreSQL, providers NLP, anonymizers, adapter dinamico y carga del catalogo.

Flujo principal de process:
1. Validacion de request y API Key.
2. Normalizacion del texto y control de longitud maxima.
3. Anonimizacion via implementacion configurada.
4. Extraccion de hallazgos contra catalogo cerrado via provider NLP.
5. Persistencia append-only del evento clinico y su auditoria.
6. Exposicion de payload clinico y trazabilidad por endpoints separados.

Decisiones vigentes:
- La API no expone request_id; la trazabilidad funcional usa process_id y la operativa usa audit_id.
- Los providers y repositorios se ensamblan desde src/api/deps.py con @lru_cache.
- La salida canonica de extraccion es {"hallazgos": [...]}.

================================================================================
5. CONTRATO API VIGENTE
================================================================================

Base path versionada:
- /api/v1

Seguridad:
- Header obligatorio: X-API-Key.
- Excepcion: endpoints health.

5.1 POST /api/v1/anamnesis/anonymize
Request:
{
  "patient_id": 12345,
  "doctor_id": 678,
  "text": "..."
}

Response 200:
{
  "process_id": "uuid",
  "patient_id": 12345,
  "doctor_id": 678,
  "anonymized_text": "..."
}

5.2 POST /api/v1/anamnesis/process
Request:
{
  "patient_id": 12345,
  "doctor_id": 678,
  "text": "..."
}

Response 200:
{
  "process_id": "uuid",
  "created_at": "2026-08-11T10:24:31Z",
  "hallazgos": [
    {"etiqueta": "...", "descripcion": "..."}
  ],
  "processing_ms": 3200
}

Nota:
- text se valida contra MAX_TEXT_LENGTH.
- El provider recibe allowed_labels del catalogo cerrado.

5.3 GET /api/v1/anamnesis/process/{process_id}
Response 200:
{
  "process_id": "uuid",
  "patient_id": 12345,
  "doctor_id": 678,
  "anonymized_text": "...",
  "hallazgos": [
    {"etiqueta": "...", "descripcion": "..."}
  ],
  "status": "success",
  "created_at": "2026-08-11T10:24:31Z"
}

Nota:
- No expone error_code, error_message ni metadata operacional.

5.4 GET /api/v1/catalog/labels
Response 200:
{
  "version": "v1",
  "labels": [{"name": "...", "description": "..."}],
  "last_updated": "2026-06-30T00:00:00Z"
}

5.5 GET /api/v1/audit/events
Response 200:
{
  "items": [
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
      "provider": "google|qwen|anonymizer",
      "provider_model": "...",
      "metadata_json": {"text_length": 1500},
      "created_at": "2026-08-11T10:24:31Z"
    }
  ],
  "page": 1,
  "page_size": 20,
  "total": 1,
  "total_pages": 1,
  "has_next": false,
  "has_prev": false
}

Regla:
- Si page excede el rango disponible, responder 400 con AUDIT_PAGE_OUT_OF_RANGE.

5.6 GET /api/v1/audit/processes/{process_id}
- Devuelve el registro de auditoria asociado a process_id.

5.7 GET /health/live
Response 200:
{
  "status": "ok"
}

5.8 GET /health
Response 200/503:
{
  "status": "healthy|degraded",
  "database": "ok|error",
  "nlp_provider": "ok|error",
  "timestamp": "2026-08-11T10:24:31Z"
}

Notas:
- /health y /health/live viven fuera de /api/v1.
- El schema de respuesta se mantiene entre 200 y 503.

5.9 Codigos HTTP relevantes
- 200 OK
- 400 Bad Request
- 401 Unauthorized
- 404 Not Found
- 408 Request Timeout
- 500 Internal Server Error
- 502 Bad Gateway
- 503 Service Unavailable

================================================================================
6. CONFIGURACION ACTUAL
================================================================================

6.1 Variables base
- APP_NAME
- LOG_LEVEL
- API_KEY
- CORS_ORIGINS
- MAX_TEXT_LENGTH
- NLP_PROVIDER_TIMEOUT_SECONDS
- PROMPT_VERSION

6.2 Base de datos
- DATABASE_DSN
- DB_SSL_MODE
- DB_SSL_CA
- DB_SSL_CERT
- DB_SSL_KEY

6.3 Anonymizer configurable
- ANONYMIZER_MODULE
- ANONYMIZER_CLASS

Estado actual del ejemplo:
- .env.example apunta a src.infrastructure.anonymizer.anonymizer.LegacySpacyAnonymizer.
- El repositorio tambien incluye una implementacion PresidioTransformerAnonymizer con dependencias instaladas.

6.4 Provider Google
- NLP_PROVIDER=google
- GOOGLE_NLP_ENDPOINT
- GOOGLE_NLP_MODEL
- GOOGLE_API_KEY
- GOOGLE_NLP_MAX_RETRIES
- GOOGLE_NLP_BASE_BACKOFF_SECONDS
- GOOGLE_NLP_MAX_BACKOFF_SECONDS

Comportamiento actual:
- El API key se envia en header x-goog-api-key.
- Hay manejo de 429 y 5xx con backoff exponencial si la configuracion habilita reintentos.

6.5 Provider Qwen
- NLP_PROVIDER=qwen
- QWEN_NLP_ENDPOINT
- QWEN_NLP_MODEL
- QWEN_API_KEY

Comportamiento actual:
- El provider soporta respuestas JSON en response, thinking o message.content.
- El endpoint por defecto del ejemplo apunta a host.docker.internal:11434/api/generate.

================================================================================
7. MODELO DE DATOS
================================================================================

7.1 Tabla anamnesis_processing_events
- process_id VARCHAR(36) PK NOT NULL
- patient_id INTEGER NOT NULL
- doctor_id INTEGER NOT NULL
- anonymized_text TEXT NOT NULL
- labels_json JSONB NOT NULL
- status ENUM process_status_enum NOT NULL
- created_at TIMESTAMPTZ NOT NULL DEFAULT now()

7.2 Tabla anamnesis_processing_audit
- audit_id VARCHAR(36) PK NOT NULL
- process_id VARCHAR(36) NOT NULL UNIQUE
- action VARCHAR(50) NOT NULL
- status ENUM process_status_enum NOT NULL
- error_code VARCHAR(50) NULL
- error_message TEXT NULL
- processing_ms INTEGER NOT NULL
- prompt_version VARCHAR(50) NOT NULL
- labels_catalog_version VARCHAR(50) NOT NULL
- provider VARCHAR(30) NOT NULL
- provider_model VARCHAR(80) NULL
- metadata_json JSONB NOT NULL
- created_at TIMESTAMPTZ NOT NULL DEFAULT now()

7.3 Cardinalidad
- events -> audit = 1:1 por UNIQUE en audit.process_id.

7.4 Estados de proceso
- success
- provider_error
- validation_error
- timeout

================================================================================
8. INMUTABILIDAD Y MIGRACIONES
================================================================================

8.1 Politica
- Persistencia append-only.
- No existen endpoints de update/delete.

8.2 Refuerzo en base
- Triggers bloquean UPDATE/DELETE en ambas tablas.

8.3 Historial de migraciones presente
- 001_initial_schema

La migracion inicial incluye:
- tablas events y audit,
- enum compartido process_status_enum,
- FK audit.process_id -> events.process_id,
- UNIQUE en audit.process_id,
- indices principales,
- funcion y triggers de inmutabilidad.

================================================================================
9. OPERACION Y SOPORTE DEL REPOSITORIO
================================================================================

9.1 Ejecucion principal
- Docker Compose levanta api y postgres.
- El entrypoint ejecuta alembic upgrade head al arranque.
- El codigo fuente src/ se monta en solo lectura dentro del contenedor api.

9.2 Directorios funcionales versionados
- src/: codigo fuente de la API.
- migrations/: versionado de esquema.

================================================================================
10. CRITERIOS DE ACEPTACION ACTUALES
================================================================================

Se considera alineado al estado del repositorio si:
- los endpoints documentados existen en src/api/v1 y src/api/v1/endpoints/health.py,
- la configuracion documentada coincide con src/config/settings.py y .env.example,
- el stack documentado coincide con requirements.txt,
- la persistencia y migraciones coinciden con migrations/versions/001_initial_schema.py.

================================================================================
11. RIESGOS Y NOTAS ABIERTAS
================================================================================

- La implementacion concreta del anonymizer depende de ANONYMIZER_MODULE/ANONYMIZER_CLASS; la documentacion no debe asumir una sola implementacion activa si no se fija en entorno.
- El ejemplo de .env sigue apuntando al anonymizer legacy, aunque el repositorio ya incluye una opcion Presidio mas pesada.
- Qwen requiere un endpoint Ollama accesible desde el entorno de ejecucion.
