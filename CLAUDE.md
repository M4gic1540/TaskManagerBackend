# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Comandos

### Setup local
```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env              # editar SECRET_KEY con un valor real
python manage.py migrate
python manage.py seed_demo        # crea admin/tecnico1/usuario1 + 1 ticket demo (passwords aleatorias, ver salida del comando)
python manage.py runserver
```

### Tests
```bash
pytest                                              # monolito completo (config.settings) — excluye gateway/ y bff/ por default
pytest tickets/tests/test_ticket_service.py -v      # un solo archivo
pytest tickets/tests/test_ticket_service.py::TestClass::test_metodo -v   # un solo test
pytest --ds=config.service_settings.tickets tickets/     # correr contra los settings de un microservicio puntual
pytest --ds=config.service_settings.gateway gateway/     # gateway/ y bff/ SOLO corren así (no tienen apps/rutas en el monolito)
```
Los tests de `TicketService`/`UserService.change_role` usan `FakeTicketRepository`/DB real según si la regla depende de `select_for_update()` (concurrencia real) o no — ver el patrón existente en `tickets/tests/` antes de agregar un test nuevo.

### Modelo de clasificación ML de tickets
```bash
python manage.py train_ticket_classifier              # dataset semilla + tickets reales de la BD
python manage.py train_ticket_classifier --seed-only   # solo semilla (sin BD; usado en el arranque de servicios sin la app tickets)
```
El artefacto (`tickets/ml/model/*.joblib`) está gitignoreado y se regenera en cada arranque de contenedor vía `entrypoint.sh`.

### Ingesta de correo (poller)
```bash
python manage.py poll_inbound_email          # loop infinito, cada INBOUND_EMAIL_POLL_INTERVAL_SECONDS
python manage.py poll_inbound_email --once   # un solo ciclo, útil para debugging
```
No-op si `INBOUND_EMAIL_HOST` está vacío.

### Docker
```bash
docker compose up --build   # levanta los 6 servicios (accounts/tickets/inventory/gateway/bff) + 3 Postgres + Redis
```
La imagen es una sola; qué app/urls carga cada contenedor depende de `SERVICE_SETTINGS` (build arg) → `DJANGO_SETTINGS_MODULE` en runtime (ver Arquitectura).

### Documentación interactiva de la API
`GET /api/docs/` (Swagger UI), `/api/redoc/`, `/api/schema/` — generada por `drf-spectacular` desde serializers, sin YAML manual.

## Arquitectura

### Un repo, seis despliegues (monolito modular)
Todo el código vive en un solo árbol Django (`accounts/`, `tickets/`, `inventory/`, `core/`, `bff/`, `gateway/`). Qué se ejecuta depende de la variable `DJANGO_SETTINGS_MODULE`:
- `config.settings` → monolito: todas las apps, una sola BD.
- `config.service_settings.{accounts,tickets,inventory,gateway,bff}` → un microservicio recortado, con su propio `ROOT_URLCONF` (`config/urls_<servicio>.py`), `INSTALLED_APPS` reducido y (en producción) su propia BD Postgres. `config/service_settings/base.py` reexporta `config.settings` con `import *` y cada archivo de servicio sobreescribe lo necesario.

Cambiar de topología es una variable de entorno, no una reescritura — la lógica de negocio (Services/Repositories/EventBus) es compartida vía `core/`.

### Capas dentro de `tickets/` e `inventory/`
```
API (vistas DRF, delgadas — reciben request, validan forma, llaman al Service)
  ↓
Service Layer (services/) — ÚNICA capa con reglas de negocio
  ↓
Repository (repositories/) — único punto que toca el ORM directamente
  ↓
Modelos
```
Nunca agregues lógica de negocio en una vista o serializer ni llames `Model.objects` desde un Service — rompe el contrato de testeo con `FakeRepository` que ya usan los tests existentes.

Patrones de soporte, todos con implementaciones concretas a seguir como precedente antes de improvisar uno nuevo:
- **Factory** (`factories/`): construcción del payload de creación, ciega de detalles para el Service.
- **Strategy** (`strategies/status_transitions.py`): una clase por estado de ticket, cada una declara sus transiciones válidas y los roles permitidos — agregar un estado nuevo es agregar una clase, no tocar un `if/elif`.
- **Observer** (`observers.py` + `events.py`, registrado en `apps.py::ready()`): `EventBus` en memoria desacopla efectos secundarios (auditoría, notificación por correo, clasificación ML) de la lógica principal. Los eventos se publican en `transaction.on_commit`, nunca antes — los observers releen el registro por id y publicar antes del commit produce `EntityNotFoundError`.
- **Specification** (`specifications/`): filtros y scoping por rol componibles con `&`/`|`/`~` sobre `Q()`, en vez de queries ad-hoc duplicadas por vista.

### Identidad sin base de datos compartida
`tickets`/`inventory` no tienen tabla de usuarios propia. `core/auth/jwt_claims_authentication.py::JWTClaimsAuthentication` resuelve identidad **100% desde los claims del JWT** (`role`, `username`, `is_active_technician`), sin consultar `accounts` por red. Por eso `assign_technician` no puede validar en BD que un id sea realmente técnico — es un trade-off aceptado, no un descuido.

### Asincronía híbrida
Las vistas de `tickets/api/views.py` son `async def` (vía `adrf`), pero el Service Layer sigue siendo síncrono porque el ORM de Django lo es. `core/async_support/bridge.py::to_async()` envuelve el Service con `sync_to_async(..., thread_sensitive=True)`; `fire_and_forget()` lanza corutinas de background (notificaciones, clasificación ML) desde código sync registrando el loop principal vía `LoopRegisteringMixin`. Las relaciones lazy (`comments`, `time_logs`) se materializan **dentro** del thread sync antes de volver a la vista async, o DRF dispara `SynchronousOnlyOperation`.

### Flujo email → ticket → clasificación ML
`tickets/management/commands/poll_inbound_email.py` (proceso de larga duración, IMAP genérico) crea tickets idempotentemente por `Message-ID` (`Ticket.external_message_id`, unique/nullable); si el asunto matchea el código de un ticket existente (`TCK-[0-9A-Z]{8}`), agrega un comentario en vez de duplicar. La creación dispara `TicketCreated` → el Observer llama en background a `tickets/ml/classifier.py` (TF-IDF + LogisticRegression local, sin servicios externos) y aplica la categoría sugerida solo si supera `TICKET_AI_CONFIDENCE_THRESHOLD`.

### BFF + Gateway (topología de microservicios)
`bff/` guarda el JWT server-side en sesión (Redis) — el browser solo tiene una cookie httpOnly, nunca el token. `bff/session.py::get_valid_access_token()` refresca transparentemente con un lock distribuido para evitar quemar el refresh token bajo requests concurrentes (`ROTATE_REFRESH_TOKENS=True`). `gateway/views.py` es un proxy sin autenticación propia que enruta por prefijo de path hacia `accounts`/`tickets`/`inventory` — la validación del JWT ocurre en el servicio destino, no en el gateway.

### Integración GLPI
`inventory/services/glpi_service.py` consulta en vivo y solo lectura una BD MariaDB externa de GLPI vía SQL crudo. Nombres de tabla siempre contra whitelist (`_safe_table_identifier`), valores siempre parametrizados. Protegida con circuit breaker (`core/resilience/circuit_breaker.py`, solo para esta dependencia externa) + cache-aside (`GLPI_CACHE_TTL_SECONDS`).

### Manejo de errores y trazabilidad
Jerarquía `DomainError` (`core/exceptions.py`) → `EntityNotFoundError`/`PermissionDeniedError`/`InvalidStateTransitionError`/`ValidationError`/`GLPIUnavailableError`, mapeada globalmente a HTTP en `core/api/exception_handler.py`. Todo request tiene un `request_id` (contextvars, no thread-local, seguro bajo ASGI) propagado a logs y eventos de dominio vía `core/tracing/`.

## Recursos del proyecto

- **Subagentes especializados** en `.claude/agents/`: `security-pentester`, `infra-reviewer`, `qa-tester`, `senior-developer`, `dba` reportan hallazgos (nunca cierran una tarea por su cuenta) a `lead-orchestrator`, que consolida el veredicto final solo cuando todos terminaron. Usalos para auditorías; ninguno modifica código por defecto.
- **Documentación de negocio y arquitectura** (RF/RNF, flujos, patrones) vive en Obsidian, en `Proyectos/Ticketera-CMM/`, no en este repo — está organizada como una red de notas interconectadas partiendo de `Hub-Ticketera-CMM.md`.
