# ASDP — Backend (Django + DRF)

Sistema de gestión de tickets IT e inventario de activos, con integración
de lectura a GLPI. 3 roles (Administrador, Técnico, Usuario), JWT auth,
arquitectura en capas (Repository / Service Layer / Factory / Strategy /
Observer / Specification), y capacidad de correr como monolito o como
4 microservicios independientes (accounts / tickets / inventory / gateway)
sobre el mismo código.

## Stack

- Python 3.13, Django 6.0, Django REST Framework 3.17, `adrf` (vistas async)
- SQLite (dev, una BD por servicio si corre en modo microservicios) —
  cambiar `DATABASES` en `config/settings.py` para Postgres
- JWT vía `djangorestframework-simplejwt` (access 15 min, refresh 7 días,
  rotación + blacklist)
- `PyMySQL` — conexión de solo lectura a la BD externa MariaDB de GLPI
- `qrcode` + `Pillow` — generación de códigos QR y etiquetas imprimibles
- `openpyxl` — import de planillas legacy de inventario (`.csv`/`.xlsx`)
- `pybreaker` — circuit breaker sobre las llamadas a GLPI
- `httpx` — cliente del API Gateway para reenviar requests a los microservicios
- `django-ratelimit` (rate limiting), `django-cors-headers`, `python-decouple` (env vars)
- Docker + Jenkins (test/coverage, SonarQube Quality Gate, build y push a DockerHub)

## Arquitectura de capas

```
config/                  settings, urls raíz, WSGI/ASGI
  service_settings/      settings alternativos por microservicio (ver más abajo)
core/                    infraestructura transversal
  events/base.py                 Observer Pattern (EventBus en memoria)
  specifications/base.py         Specification Pattern (Q() componibles)
  repositories/base.py           Repository Pattern (contrato genérico)
  exceptions.py                  Excepciones de dominio
  middleware.py                  Security headers
  api/exception_handler.py       Mapea DomainError -> HTTP
  auth/jwt_claims_authentication.py  Auth basada en claims del JWT (microservicios)
  resilience/circuit_breaker.py  Circuit breaker (llamadas a GLPI)
  health/                        Liveness/Readiness checks
  async_support/                 Puente sync/async para vistas adrf

accounts/        Usuario custom (roles), JWT, RBAC
  models.py              User con campo `role`
  permissions.py         IsAdmin / IsTechnician / IsRequester / object-level
  api/                   serializers + views (login, registro, gestión técnicos)

tickets/         Dominio de gestión de tickets
  models.py              Ticket, TicketComment, TicketAttachment, TicketTimeLog
  factories/             Factory Pattern (prioridad por categoría)
  strategies/            Strategy Pattern (transiciones de estado por rol)
  specifications/        Specs concretas (por status/prioridad/categoría/dueño)
  repositories/          TicketRepository (único punto que toca el ORM)
  services/              TicketService (orquesta todo — única lógica de negocio)
  events.py              Eventos de dominio (TicketCreated, TicketAssigned, ...)
  observers.py           Observers concretos (auditoría, notificaciones)
  api/                   serializers + views (delgadas, delegan a Service)

inventory/       Dominio de gestión de activos + integración GLPI
  models.py              Asset, AssetHistory
  services/asset_service.py   CRUD, QR, import legacy, export .zip
  services/glpi_service.py    Lectura en vivo a MariaDB de GLPI (solo SELECT)
  services/qr_label.py        Composición de la imagen de etiqueta QR
  services/dashboard_service.py  KPIs de inventario (solo Admin)
  import_parser.py / import_mapping.py  Parseo de planillas legacy (CSV/XLSX)
  api/                   serializers + views

gateway/          API Gateway (reverse proxy hacia accounts/tickets/inventory)
  views.py                GatewayProxyView
```

### Por qué estas capas

- **Repository**: los `Service` nunca llaman `Ticket.objects`/`Asset.objects`
  directo. Permite testear lógica de negocio con un Fake Repository en
  memoria (ver `tickets/tests/`), sin base de datos — Dependency Inversion
  Principle en la práctica.
- **Service Layer**: única capa con reglas de negocio. Las vistas DRF son
  delgadas (reciben request, validan input, llaman Service, serializan output).
- **Factory**: `TicketFactory` decide la prioridad default según categoría
  sin ensuciar el Service con `if/elif`.
- **Strategy**: cada estado (`ABIERTO`, `ASIGNADO`, ...) tiene su propia clase
  de transición válida + roles permitidos. Agregar un estado nuevo no toca
  código existente (Open/Closed Principle).
- **Observer**: `EventBus` desacopla efectos secundarios (auditoría, notificaciones)
  de la lógica principal. El `TicketService`/`UserService` publican eventos; no
  saben quién escucha ni qué hacen los observers.
- **Specification**: filtros de listado y el scoping por rol se componen
  con `&`/`|`/`~` sin duplicar queries.

## Módulo de Inventario

Cada activo (`Asset`) tiene un código correlativo interno legible
(`AST-XXXXXXXX`) y un identificador público no correlativo (`public_uuid`,
UUID v4) — este último, no el `id`, es el que se codifica en el QR y se
expone en la vista pública, para que no se puedan enumerar activos
probando URLs consecutivas.

- **CRUD + QR**: crear/editar/eliminar activos (Admin/Técnico), con
  generación y regeneración automática del código QR.
- **Vista pública de escaneo**: `GET /inventory/public/<uuid>/`, sin
  autenticación — es lo que resuelve el navegador al escanear el QR
  físico de la etiqueta.
- **Etiquetas imprimibles**: exportación en `.zip` con una imagen PNG
  por activo (QR + número de serie + N° de inventario), pensada para
  enviarse directo al software de impresión de una Brother QL-800.
- **Import legacy**: sube una planilla `.csv`/`.xlsx` (máx. 10MB) y
  crea un `Asset` por fila, deduplicando por `(legacy_id, serial_number)`
  para que la misma planilla se pueda re-subir sin generar duplicados;
  una fila con datos malos no tumba el resto del batch.
- **Dashboard ejecutivo** (solo Admin): conteos por estado/categoría,
  activos disponibles, sin responsable asignado, top 5 ubicaciones y
  resumen de garantías (vencidas / por vencer en 30 días).

### Integración de solo lectura con GLPI

`GLPIInventoryService` consulta en vivo, vía una segunda conexión de
base de datos (alias `"glpi"`, MariaDB externa), las tablas nativas de
GLPI (`glpi_computers`, `glpi_monitors`, `glpi_printers`,
`glpi_networkequipments`, `glpi_peripherals`, `glpi_phones`) — sin ORM
ni migraciones sobre esa base, solo SQL crudo de solo lectura.

- **Defensa contra inyección SQL**: los nombres de tabla nunca vienen de
  input externo — se resuelven contra una whitelist fija
  (`TABLE_MAPPING`) y se quotean vía `connection.ops.quote_name()`
  antes de sustituirse en plantillas SQL estáticas con `str.replace()`
  (nunca f-string/`.format()`); los valores siempre van por bind
  params (`%s`).
- **Cache-aside**: `list_assets()` y `get_dashboard_summary()` cachean
  su resultado (`GLPI_CACHE_TTL_SECONDS`, default 60s) antes de tocar
  la BD externa, para no recalcular en cada refresh de pantalla.
- **Circuit breaker** (`core/resilience/circuit_breaker.py`, vía
  `pybreaker`): si GLPI empieza a fallar (`GLPI_BREAKER_FAIL_MAX`
  fallos seguidos), el breaker se abre por `GLPI_BREAKER_RESET_TIMEOUT`
  segundos y las siguientes llamadas fallan rápido con un error de
  dominio (`GLPIUnavailableError`) en vez de colgar la request
  esperando un timeout de red contra una base caída.
- Los activos que todavía viven solo en GLPI (no migrados a `Asset`)
  generan un QR que apunta directo al formulario del activo en la UI
  de GLPI, no a la vista pública propia.

## API Gateway y microservicios

El mismo código puede correr como **monolito** (`config.settings`, todo
en un proceso/una BD, como hasta ahora) o como **4 microservicios**
independientes, eligiendo el `DJANGO_SETTINGS_MODULE`:

| Servicio | Settings | Responsabilidad |
|---|---|---|
| `accounts` | `config.service_settings.accounts` | Dueño de la tabla `User` real, emite/refresca/blacklistea JWT |
| `tickets` | `config.service_settings.tickets` | Dominio de tickets, sin `accounts` instalado |
| `inventory` | `config.service_settings.inventory` | Dominio de inventario + conexión a GLPI |
| `gateway` | `config.service_settings.gateway` | Único punto expuesto al navegador; reverse proxy |

`tickets` e `inventory` no tienen la tabla `User` en su propia base:
resuelven la identidad **enteramente desde los claims del JWT**
(`core/auth/jwt_claims_authentication.py`, `JWTClaimsAuthentication` +
`TokenClaimsUser`), validando solo la firma/expiración del token —
nunca consultan una tabla de usuarios local.

El **Gateway** (`gateway/views.py`, `GatewayProxyView`) es un reverse
proxy transparente que preserva las rutas `/api/v1/...` tal cual las
consume el frontend, reenviando a cada servicio interno vía `httpx`:

```
/api/v1/tickets/...     -> TICKETS_SERVICE_URL
/api/v1/inventory/...   -> INVENTORY_SERVICE_URL
/api/v1/...  (resto)    -> ACCOUNTS_SERVICE_URL
```

El Gateway no valida el JWT (solo lo reenvía tal cual en `Authorization`)
— cada servicio downstream lo valida por su cuenta. Timeouts de
red se mapean a `503`/`504` en vez de colgar la request.

**Correr un microservicio individual** (en vez del monolito):

```bash
docker build --build-arg SERVICE_SETTINGS=config.service_settings.tickets .
```

**Correr los 4 juntos con Docker Compose** (recomendado para probar el
sistema completo en local):

```bash
cp .env.example .env   # completar SECRET_KEY y GLPI_DB_*
docker compose up --build
```

Solo el `gateway` expone puerto al host (`8000`); los otros 3 servicios
solo son alcanzables dentro de la red interna del compose. Cada uno
tiene su propio healthcheck contra `/readyz/`.

## Health checks

Registrados por servicio (`core/health/registry.py`), disponibles en
toda variante de settings (monolito y los 4 microservicios):

```
GET /healthz/    liveness — siempre 200 si el proceso está vivo, sin dependencias
GET /readyz/     readiness — 200 si todos los checks registrados pasan, 503 si no
```

El monolito y `inventory` registran, además de la conexión a su propia
base de datos, un check del estado del circuit breaker de GLPI (sin
abrir una conexión nueva — evita que el propio probe de salud tumbe
más una GLPI ya caída).

## Roles y permisos (RBAC)

| Acción | Admin | Técnico | Usuario |
|---|---|---|---|
| Crear ticket | ✓ | ✓ | ✓ |
| Ver todos los tickets | ✓ | solo asignados | solo propios |
| Asignar técnico | ✓ | ✗ | ✗ |
| Cambiar estado | ✓ | ✓ (asignado) | ✓ (limitado, ver Strategy) |
| Cerrar ticket (con nota) | ✓ | ✓ | ✗ |
| Registrar tiempo trabajado | ✗ | ✓ (solo asignado) | ✗ |
| Comentar | ✓ | ✓ | ✓ |
| Gestionar usuarios/técnicos | ✓ | ✗ | ✗ |
| Registrar/editar/regenerar QR de activo | ✓ | ✓ | ✗ |
| Eliminar activo | ✓ | ✗ | ✗ |
| Ver dashboard de inventario | ✓ | ✗ | ✗ |

La vista pública de detalle de un activo (`GET /inventory/public/<uuid>/`,
la que resuelve el QR escaneado) no requiere autenticación — es visible
para cualquiera que tenga el link/QR físico.

## Seguridad implementada

- JWT con claims custom (`role`, `username`) — el frontend no necesita
  otro request para saber el rol.
- Refresh token con rotación + blacklist (`ROTATE_REFRESH_TOKENS`,
  `BLACKLIST_AFTER_ROTATION`).
- Password hasheado con PBKDF2-SHA256 (default Django, nunca texto plano).
- Rate limiting: `5/min` en login (`django-ratelimit`), `120/min` autenticado
  y `20/min` anónimo a nivel global (DRF throttling).
- Security headers custom (`CSP`, `Referrer-Policy`, `Permissions-Policy`,
  `X-Content-Type-Options`) + `SecurityMiddleware` de Django.
- HTTPS-ready: `SECURE_SSL_REDIRECT`, `SECURE_HSTS_*`, cookies `Secure`
  activables por variable de entorno para producción.
- CORS restringido a orígenes explícitos (`CORS_ALLOWED_ORIGINS`), solo
  configurado en el Gateway.
- Validación de contraseña reforzada (mínimo 10 caracteres + validators de Django).
- Manejo global de excepciones: `DomainError` se mapea a HTTP consistente
  sin try/except repetido en cada vista.
- Consultas a la BD externa de GLPI con nombres de tabla whitelisteados
  (nunca interpolación de input externo) y valores siempre por bind param.
- Identificadores públicos de activos (`public_uuid`) no correlativos,
  para que no se puedan enumerar activos por URL.
- Contenedor Docker corre como usuario sin privilegios (no `root`); solo
  `staticfiles/`, `media/` y `data/` son escribibles en runtime, el resto
  del código queda de solo lectura.

## Trazabilidad HTTP

Toda petición recibe un `request_id` único (`core/tracing/`):

- **`RequestTracingMiddleware`** (primero en la cadena): genera un ID
  (o reusa `X-Request-ID` si el cliente ya lo mandó), lo guarda en
  `contextvars` y lo devuelve en el header `X-Request-ID` de la respuesta.
- **Logging**: cada log (`ticketera.request`, `ticketera` de servicios,
  auditoría de Observer) incluye automáticamente `req=<id> user=<id>`
  vía `RequestTracingFilter`, sin que ningún `logger.info(...)` tenga
  que pasarlo a mano.
- **Errores**: el `exception_handler` global agrega `request_id` al
  body de toda respuesta de error — el usuario puede reportar ese ID
  exacto a soporte para buscar en logs.
- **Eventos de dominio**: `DomainEvent` (Observer Pattern) incluye
  `request_id` automáticamente, así la auditoría queda correlacionada
  con la petición HTTP que la disparó.
- Como usa `contextvars` (no un `threading.local` global), es seguro
  también si a futuro se corre bajo ASGI/async.

Ejemplo de log de una petición:
```
-> POST /api/v1/tickets/1/assign/
<- POST /api/v1/tickets/1/assign/ 403 2.6ms
AUDIT ticket_assigned id=1 technician=2 by=1 req=f95b403382b44a8f
```

## Dashboard ejecutivo (solo Admin)

`GET /api/v1/tickets/dashboard/` — requisito explícito del rol
Administrador. Agregación de solo lectura (`tickets/services/dashboard_service.py`),
sin efectos secundarios ni eventos (es un reporte, no una operación de negocio).

Incluye:
- **Conteos** por estado, prioridad y categoría, más total y "abiertos".
- **Tiempo promedio de resolución** por prioridad (horas entre `created_at`
  y `closed_at`, solo tickets `CERRADO`).
- **SLA vencido por prioridad**: tickets aún abiertos cuyo tiempo desde
  creación supera el límite configurado en `settings.TICKET_SLA_HOURS`:

  | Prioridad | SLA |
  |---|---|
  | CRITICA | 2h |
  | ALTA | 4h |
  | MEDIA | 8h |
  | BAJA | 24h |

  Un ticket ya cerrado nunca cuenta como vencido, aunque haya tardado
  más que el SLA — la métrica mide "sigue abierto más allá del límite",
  no la duración de resolución en sí (esa es `avg_resolution_hours`).

Ejemplo de respuesta:
```json
{
  "by_status": {"ABIERTO": 1, "ASIGNADO": 2, "CERRADO": 1},
  "by_priority": {"ALTA": 1, "CRITICA": 1, "MEDIA": 2},
  "by_category": {"HARDWARE": 2, "RED": 1, "SOFTWARE": 1},
  "total": 4,
  "open_total": 3,
  "avg_resolution_hours": {"MEDIA": 6.0},
  "sla": {
    "sla_hours_config": {"CRITICA": 2, "ALTA": 4, "MEDIA": 8, "BAJA": 24},
    "breached_by_priority": {"CRITICA": 1, "ALTA": 0, "MEDIA": 0, "BAJA": 0},
    "total_breached": 1
  }
}
```

`GET /api/v1/inventory/dashboard/` sigue el mismo criterio para
activos (conteos por estado/categoría, disponibles, sin responsable,
top ubicaciones y resumen de garantías).

Tests con DB real (no Fake — es agregación ORM, fakearla testearía una
reimplementación manual): `tickets/tests/test_dashboard_service.py`,
`inventory/tests/test_dashboard_service.py`.

## Documentación interactiva (Swagger/OpenAPI)

Generada con `drf-spectacular`, sin anotación manual de YAML — infiere
el schema de los serializers y `@extend_schema` en cada vista.

```
GET /api/schema/       esquema OpenAPI 3 crudo (YAML/JSON)
GET /api/docs/         Swagger UI (probar endpoints desde el navegador)
GET /api/redoc/        ReDoc (documentación de lectura)
```

Para auth en Swagger UI: hacer login en `/api/v1/auth/login/`, copiar
el `access` token, y pegarlo en el botón "Authorize" como
`Bearer <token>`.

**Nota sobre CSP**: `core/middleware.py` aplica un Content-Security-Policy
estricto a toda la API (`script-src 'self'`, sin CDNs externos). Swagger
UI y ReDoc cargan su JS/CSS desde `cdn.jsdelivr.net` y usan estilos/scripts
inline, así que **solo** en `/api/docs/` y `/api/redoc/` el middleware
sirve un CSP más permisivo (`_DOCS_CSP`); el resto de rutas —incluida
`/api/schema/`— mantiene el CSP estricto original. La versión de
`swagger-ui-dist`/`redoc` está fijada en `SPECTACULAR_SETTINGS`
(no `@latest`) para que no se rompa si el CDN publica un bundle nuevo.

## Asincronía

Las vistas de `tickets/api/views.py` e `inventory/api/views.py` son
`async def`, usando `adrf` (DRF vanilla no soporta class-based views
async de forma estable — ver `core/async_support/`):

- **`core/async_support/bridge.py`** — `to_async()` envuelve el Service
  Layer (sync, porque el ORM de Django lo es) con `sync_to_async(...,
  thread_sensitive=True)`, corriendo la lógica de negocio en un
  threadpool sin bloquear el event loop. `thread_sensitive=True` es
  obligatorio: las conexiones de DB están ligadas al thread, así que
  todo el trabajo de una misma petición corre en el mismo thread.
- **`fire_and_forget()`** — lanza corutinas sin esperar su resultado
  desde código sync (usado por `TicketNotificationObserver`, que corre
  dentro del threadpool del Service). Agenda la tarea contra el event
  loop principal vía `asyncio.run_coroutine_threadsafe`; si no hay loop
  ASGI activo (management commands, tests), cae a `asyncio.run()` como
  fallback para no perder la notificación.
- **`core/async_support/mixins.py`** — `LoopRegisteringMixin` registra
  el event loop actual en cada request async, para que el Observer
  (ejecutado en otro thread) sepa dónde agendar sus tareas.

Patrón por vista: `get_ticket` (sync) se envuelve en `to_async`,
se materializan relaciones (`comments`, `time_logs`) DENTRO del thread
sync (`_serialize_detail_sync`), y solo entonces se retorna a la vista
async — DRF serializa querysets lazy, y evaluarlos fuera del thread
sync dispara `SynchronousOnlyOperation`.

Algunas vistas de inventario (import de planillas, generación de hojas
QR) son intencionalmente **síncronas** en vez de `adrf`: son CPU-bound
(parsear el archivo, componer las imágenes) y no se benefician de async,
mismo criterio en ambos módulos.

**Por qué el Service Layer sigue sync:** convertir Repository/Service
a async real (`await Ticket.objects.acreate(...)`) es posible en Django
6, pero reescribiría toda la capa de negocio y los tests con Fake
Repositories. El costo de esa migración no se justifica hoy;
`sync_to_async` da el beneficio de concurrencia en la capa HTTP (que es
donde más importa bajo carga) sin tocar Service/Repository/Strategy/Factory.

**Beneficio:** el proceso puede atender otras peticiones mientras una
espera I/O de DB o de la notificación fire-and-forget.
**Desventaja:** cada request pasa por un threadpool (`sync_to_async`)
en vez de I/O async nativo — hay overhead de cambio de contexto que un
ORM async real no tendría. Es una capa de compatibilidad, no async "puro".

## Auto-asignación de tickets (Técnico toma tickets sin asignar)

Antes, solo un Admin podía asignar técnico (`POST /tickets/<id>/assign/`).
Ahora un Técnico puede tomar directamente un ticket del "pool" de
solicitudes sin asignar:

```
GET  /api/v1/tickets/available/      pool de tickets ABIERTO sin técnico (solo Técnico)
POST /api/v1/tickets/<id>/take/      el propio técnico se auto-asigna el ticket
```

Reglas (`TicketService.self_assign`):
- Solo rol Técnico, y con `is_active_technician=True`.
- El ticket debe estar en estado `ABIERTO` y sin `assigned_technician`.
- Usa `select_for_update()` (lock de fila) para evitar que dos técnicos
  tomen el mismo ticket en una condición de carrera — probado con test
  explícito (`test_cannot_take_already_assigned_ticket`).
- Dispara el mismo evento `TicketAssigned` que la asignación por Admin
  (Observer Pattern) — la auditoría no distingue el origen del evento
  en el log, pero si hace falta diferenciarlos, se puede: `assigned_by_id`
  queda igual al `technician_id` cuando es self-assign (en vez de un
  admin distinto).

`GET /tickets/available/` es un endpoint separado del listado principal
(`GET /tickets/`) — no se mezcló con el scoping por rol existente para
no romper el contrato de "Técnico ve solo lo asignado" en el listado
normal. Es explícitamente "el pool de trabajo pendiente", no "mis tickets".

## Cambiar el rol de un usuario

Dos caminos:

1. **Django admin** (`/admin/`, modelo `User`) — rápido para setup manual.
2. **API**: `PATCH /api/v1/users/<id>/role/` (`accounts/services/user_service.py`),
   solo Admin. Reglas de negocio (Service Layer, no en la vista):
   - No podés cambiar tu propio rol (evita que un Admin se auto-degrade
     por error y quede bloqueado).
   - No se puede quitar el rol ADMIN al último administrador activo del
     sistema (protege contra quedarse sin nadie que administre).
   - Cambio idempotente: pedir el mismo rol que ya tiene no dispara
     evento ni escritura.
   - Cada cambio dispara `UserRoleChanged` (Observer Pattern, igual que
     tickets) — queda auditado con `request_id` correlacionado.

Tests con DB real (usa `select_for_update()`, no tiene sentido fakear
transacciones): `accounts/tests/test_user_service.py`.

## Setup (monolito, desarrollo local)

```bash
python3 -m venv venv
source venv/bin/activate       # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env           # editar SECRET_KEY y, si vas a probar inventory/GLPI, GLPI_DB_*
python manage.py migrate
python manage.py seed_demo     # crea admin/tecnico1/usuario1 + 1 ticket demo
python manage.py createsuperuser   # opcional, admin ya viene del seed
python manage.py runserver
```

Credenciales demo (creadas por `seed_demo`):

`seed_demo` genera contraseñas aleatorias seguras. Revisa la salida del comando para obtener las credenciales:

```
Usuario admin creado. Contraseña: <contraseña generada dinámicamente>
Usuario tecnico1 creado. Contraseña: <contraseña generada dinámicamente>
Usuario usuario1 creado. Contraseña: <contraseña generada dinámicamente>
```

## Setup (Docker / microservicios)

```bash
cp .env.example .env           # SECRET_KEY + GLPI_DB_HOST/USER/PASSWORD

docker compose up --build      # levanta accounts + tickets + inventory + gateway
```

El frontend consume todo a través del Gateway, en `http://localhost:8000`.
Para una sola imagen monolítica (sin compose): `docker build .` — el
mismo `Dockerfile` sirve para ambos casos, parametrizado por
`--build-arg SERVICE_SETTINGS=config.service_settings.<accounts|tickets|inventory|gateway>`.

## CI/CD

`Jenkinsfile` corre en cada build:

1. **Install dependencies** — venv + `pip install -r requirements.txt`.
2. **Test + coverage** — corre pytest contra el monolito y, por separado,
   contra el `DJANGO_SETTINGS_MODULE` de cada microservicio (código bajo
   `config/service_settings/*` o `gateway/` solo se ejercita ahí), y
   combina todos los reportes en un único `coverage.xml`.
3. **SonarQube analysis** + **Quality Gate** — el build falla si el
   Quality Gate no pasa.
4. **Docker build** — imagen monolítica `taskmanager-backend:<build>`.
5. **Docker push** — solo en la rama `produccion`: taggea y sube la
   imagen a DockerHub (`m4gic/gestorinventario:<build>` y `:latest`).
   El resto de las ramas (`feature`, `develop`, etc.) comparten el mismo
   tag `:latest` del repo, así que solo `produccion` publica, para que
   no se pisen entre sí.

## Tests

```bash
pytest tickets/ inventory/ accounts/ core/ -v          # contra el monolito
pytest --ds=config.service_settings.gateway gateway/ -v  # microservicio aislado
```

Los tests de `TicketService`/`AssetService` usan Fake Repositories (sin
DB real) donde tiene sentido, demostrando que el Service depende de una
abstracción, no del ORM. Los tests que ejercitan `select_for_update()`,
agregaciones ORM, o la conexión a GLPI (con un `glpi_schema` fixture
que arma tablas de prueba) sí usan una base real, porque fakearlos
reimplementaría la lógica que se busca probar.

## Endpoints principales

```
POST   /api/v1/auth/register/            registro público (rol USUARIO)
POST   /api/v1/auth/login/               login -> access + refresh
POST   /api/v1/auth/refresh/             renovar access token
POST   /api/v1/auth/logout/              blacklist del refresh token
GET    /api/v1/me/                       perfil propio

GET    /api/v1/technicians/              listar técnicos/admins (solo Admin)
POST   /api/v1/technicians/              crear técnico/admin (solo Admin)
PATCH  /api/v1/technicians/<id>/deactivate/   activar/desactivar técnico
PATCH  /api/v1/users/<id>/role/          cambiar rol de usuario (solo Admin)

GET    /api/v1/tickets/?status=&priority=&category=&search=   listar (scoped por rol)
GET    /api/v1/tickets/available/        pool de tickets sin asignar (solo Técnico)
POST   /api/v1/tickets/                  crear ticket
GET    /api/v1/tickets/<id>/             detalle
POST   /api/v1/tickets/<id>/assign/      asignar técnico (solo Admin)
POST   /api/v1/tickets/<id>/take/        auto-asignarse un ticket sin asignar (Técnico)
POST   /api/v1/tickets/<id>/status/      cambiar estado (Strategy valida)
POST   /api/v1/tickets/<id>/close/       cerrar con nota de resolución obligatoria
POST   /api/v1/tickets/<id>/comments/    agregar comentario
POST   /api/v1/tickets/<id>/time-logs/   registrar tiempo trabajado (solo Técnico)
GET    /api/v1/tickets/dashboard/        dashboard ejecutivo con KPIs (solo Admin)

GET    /api/v1/inventory/?status=&category=&search=   listar activos (Admin/Técnico)
POST   /api/v1/inventory/                crear activo (genera QR automático)
GET    /api/v1/inventory/<id>/           detalle
PATCH  /api/v1/inventory/<id>/           editar activo
DELETE /api/v1/inventory/<id>/           eliminar activo (solo Admin)
POST   /api/v1/inventory/<id>/regenerate-qr/   regenerar QR
GET    /api/v1/inventory/public/<uuid>/  detalle público (sin autenticación, vía QR escaneado)
POST   /api/v1/inventory/import/         importar planilla legacy (.csv/.xlsx, máx. 10MB)
GET    /api/v1/inventory/qr-images/?ids= exportar .zip de etiquetas QR (activos locales)
GET    /api/v1/inventory/dashboard/      dashboard ejecutivo de inventario (solo Admin)
GET    /api/v1/inventory/glpi/           listar activos en vivo desde GLPI
GET    /api/v1/inventory/glpi/summary/   dashboard de KPIs en vivo desde GLPI
GET    /api/v1/inventory/glpi/qr-images/?ids=  exportar .zip de etiquetas QR (activos GLPI)

GET    /healthz/                         liveness probe
GET    /readyz/                          readiness probe (DB + circuit breaker GLPI)

GET    /api/docs/                        Swagger UI
GET    /api/redoc/                       ReDoc
GET    /api/schema/                      OpenAPI schema crudo
```

## Siguientes pasos sugeridos

- ~~Swagger/OpenAPI (`drf-spectacular`) para documentación interactiva.~~ ✅ implementado
- ~~Endpoint de dashboard ejecutivo con KPIs agregados.~~ ✅ implementado
- ~~Desacoplar el monolito en microservicios independientes.~~ ✅ implementado
- ~~Pipeline de CI/CD con tests, Quality Gate y build de imagen Docker.~~ ✅ implementado
- Migrar `EventBus` a colas reales (RabbitMQ/Celery) si el volumen lo justifica.
- Migrar SQLite -> PostgreSQL para producción (cambio aislado en `settings.py`).
- Circuit breaker entre los microservicios internos (Gateway <-> accounts/tickets/inventory),
  hoy solo existe entre `inventory` y la BD externa de GLPI.
