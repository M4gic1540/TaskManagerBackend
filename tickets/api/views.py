"""Vistas async: DRF vanilla no soporta `async def` en class-based
views, se usa `adrf` (async support para DRF). El Service Layer sigue
siendo sync (el ORM de Django lo es), así que cada llamada al Service
se envuelve con `sync_to_async` (core/async_support/bridge.py) para no
bloquear el event loop mientras espera la DB."""
from adrf.generics import GenericAPIView as AsyncGenericAPIView
from adrf.views import APIView as AsyncAPIView
from drf_spectacular.utils import OpenApiParameter, extend_schema

from accounts.enums import Role
from accounts.permissions import (
    IsAdmin,
    IsOwnerOrAssignedTechnicianOrAdmin,
    IsOwnerOrTechnicianOrAdmin,
)
from core.async_support.bridge import to_async
from core.async_support.mixins import LoopRegisteringMixin
from core.specifications.base import AlwaysTrueSpecification
from rest_framework import permissions, status
from rest_framework.response import Response
from tickets.models import ResponseTemplate, TicketStatus
from tickets.api.serializers import (
    DashboardSummarySerializer,
    ResponseTemplateSerializer,
    TicketAssignSerializer,
    TicketCloseSerializer,
    TicketCommentCreateSerializer,
    TicketCommentSerializer,
    TicketCreateSerializer,
    TicketDetailSerializer,
    TicketListSerializer,
    TicketStatusChangeSerializer,
    TicketTimeLogCreateSerializer,
    TicketTimeLogSerializer,
)
from tickets.services.dashboard_service import DashboardService
from tickets.services.ticket_service import TicketService
from tickets.specifications.ticket_specs import (
    TicketAssignedToSpec,
    TicketByCategorySpec,
    TicketByStatusSpec,
    TicketRequestedBySpec,
    TicketSearchTextSpec,
    TicketUnassignedSpec,
)


def _scope_by_role_spec(user):
    """RBAC a nivel de datos: Usuario ve solo lo suyo, Técnico ve lo
    asignado, Admin ve todo. Construido con Specification Pattern."""
    if user.role == Role.ADMIN or user.is_superuser:
        return AlwaysTrueSpecification()
    if user.role == Role.TECNICO:
        return TicketAssignedToSpec(user.id)
    return TicketRequestedBySpec(user.id)


def _build_filter_spec(query_params):
    spec = AlwaysTrueSpecification()
    if status_ := query_params.get("status"):
        spec = spec & TicketByStatusSpec(status_)
    if category := query_params.get("category"):
        spec = spec & TicketByCategorySpec(category)
    if search := query_params.get("search"):
        spec = spec & TicketSearchTextSpec(search)
    return spec


def _list_tickets_sync(user, query_params):
    """Corre en threadpool: evalúa el queryset (I/O de DB) y lo
    materializa a lista de dicts vía serializer, todo dentro del mismo
    thread (thread_sensitive) porque el ORM lo exige."""
    service = TicketService()
    role_spec = _scope_by_role_spec(user)
    filter_spec = _build_filter_spec(query_params)
    queryset = service.list_tickets(role_spec & filter_spec)
    return list(queryset)


def _list_available_tickets_sync(query_params):
    """Tickets ABIERTO y sin técnico asignado: el pool de trabajo que
    cualquier Técnico puede tomar. No aplica scoping por dueño/asignado
    porque, por definición, todavía no tienen asignado a nadie."""
    service = TicketService()
    filter_spec = TicketUnassignedSpec() & TicketByStatusSpec(TicketStatus.ABIERTO)
    filter_spec = filter_spec & _build_filter_spec(query_params)
    return list(service.list_tickets(filter_spec))


def _get_ticket_sync(ticket_id: int):
    """Corre en threadpool: obtiene el ticket y fuerza evaluación de
    relaciones (comments, time_logs, attachments) ANTES de salir del
    thread sync, porque el serializer las recorre fuera de él."""
    ticket = TicketService().get_ticket(ticket_id)
    list(ticket.comments.all())
    list(ticket.time_logs.all())
    list(ticket.attachments.all())
    return ticket


def _serialize_detail_sync(ticket) -> dict:
    """Serializa a dict plano DENTRO del thread sync (recorre
    relaciones lazy), para que la vista async solo maneje datos ya
    materializados."""
    list(ticket.comments.all())
    list(ticket.time_logs.all())
    list(ticket.attachments.all())
    return TicketDetailSerializer(ticket).data


class TicketListCreateView(LoopRegisteringMixin, AsyncGenericAPIView):
    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = TicketListSerializer

    @extend_schema(
        summary="Listar tickets (scoped por rol)",
        description=(
            "Usuario ve solo sus tickets, Técnico ve los asignados, "
            "Admin ve todos. Filtros combinables vía Specification Pattern."
        ),
        parameters=[
            OpenApiParameter("status", str, description="Filtrar por estado exacto"),
            OpenApiParameter("category", str, description="Filtrar por categoría exacta"),
            OpenApiParameter("search", str, description="Búsqueda en título/descripción/código"),
        ],
        responses=TicketListSerializer(many=True),
    )
    async def get(self, request):
        tickets = await to_async(_list_tickets_sync)(request.user, request.query_params)
        page = self.paginate_queryset(tickets)
        serializer = TicketListSerializer(page, many=True)
        return self.get_paginated_response(serializer.data)

    @extend_schema(
        summary="Crear ticket",
        request=TicketCreateSerializer,
        responses={201: TicketDetailSerializer},
    )
    async def post(self, request):
        serializer = TicketCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        create_ticket = to_async(TicketService().create_ticket)
        ticket = await create_ticket(requester=request.user, **serializer.validated_data)

        serialize = to_async(_serialize_detail_sync)
        data = await serialize(ticket)
        return Response(data, status=status.HTTP_201_CREATED)


class TicketAvailableListView(LoopRegisteringMixin, AsyncGenericAPIView):
    """Pool de tickets ABIERTO sin técnico asignado — lo que un
    Técnico puede tomar (self-assign). Solo rol Técnico, cualquiera
    puede ver este pool (no hay dueño todavía)."""

    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = TicketListSerializer

    @extend_schema(
        summary="Listar tickets disponibles para tomar (sin asignar)",
        description="Tickets en estado ABIERTO sin técnico asignado. Cualquier Técnico puede tomarlos.",
        responses=TicketListSerializer(many=True),
    )
    async def get(self, request):
        if request.user.role != Role.TECNICO and not request.user.is_superuser:
            return Response(
                {"detail": "Solo un Técnico puede ver el pool de tickets disponibles."},
                status=status.HTTP_403_FORBIDDEN,
            )
        tickets = await to_async(_list_available_tickets_sync)(request.query_params)
        page = self.paginate_queryset(tickets)
        serializer = TicketListSerializer(page, many=True)
        return self.get_paginated_response(serializer.data)


class TicketTakeView(LoopRegisteringMixin, AsyncAPIView):
    """Un Técnico toma (self-assign) un ticket sin asignar. Distinto de
    TicketAssignView (que es un Admin asignando a un tercero)."""

    permission_classes = (permissions.IsAuthenticated,)

    @extend_schema(
        summary="Tomar ticket sin asignar (Técnico)",
        description=(
            "El propio Técnico se auto-asigna un ticket en estado ABIERTO "
            "y sin técnico asignado. Pasa a ASIGNADO. Usa select_for_update "
            "para evitar que dos técnicos tomen el mismo ticket a la vez."
        ),
        request=None,
        responses=TicketDetailSerializer,
    )
    async def post(self, request, ticket_id: int):
        self_assign = to_async(TicketService().self_assign)
        ticket = await self_assign(ticket_id=ticket_id, technician=request.user)

        serialize = to_async(_serialize_detail_sync)
        data = await serialize(ticket)
        return Response(data)


class TicketDetailView(LoopRegisteringMixin, AsyncAPIView):
    permission_classes = (permissions.IsAuthenticated, IsOwnerOrTechnicianOrAdmin)

    @extend_schema(
        summary="Detalle de ticket",
        description="Incluye comentarios, tiempo trabajado y adjuntos.",
        responses=TicketDetailSerializer,
    )
    async def get(self, request, ticket_id: int):
        get_ticket = to_async(_get_ticket_sync)
        ticket = await get_ticket(ticket_id)
        self.check_object_permissions(request, ticket)

        serialize = to_async(_serialize_detail_sync)
        data = await serialize(ticket)
        return Response(data)


class TicketAssignView(LoopRegisteringMixin, AsyncAPIView):
    """Solo Admin asigna técnico (regla de negocio del rol Administrador)."""

    permission_classes = (IsAdmin,)

    @extend_schema(
        summary="Asignar técnico (solo Admin)",
        request=TicketAssignSerializer,
        responses=TicketDetailSerializer,
    )
    async def post(self, request, ticket_id: int):
        serializer = TicketAssignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        assign = to_async(TicketService().assign_technician)
        ticket = await assign(
            ticket_id=ticket_id,
            technician_id=serializer.validated_data["technician_id"],
            technician_username=serializer.validated_data["technician_username"],
            actor=request.user,
        )

        serialize = to_async(_serialize_detail_sync)
        data = await serialize(ticket)
        return Response(data)


class TicketStatusChangeView(LoopRegisteringMixin, AsyncAPIView):
    permission_classes = (permissions.IsAuthenticated, IsOwnerOrAssignedTechnicianOrAdmin)

    @extend_schema(
        summary="Cambiar estado de ticket",
        description="Transición validada por Strategy Pattern según estado actual y rol del actor.",
        request=TicketStatusChangeSerializer,
        responses=TicketDetailSerializer,
    )
    async def post(self, request, ticket_id: int):
        get_ticket = to_async(_get_ticket_sync)
        ticket = await get_ticket(ticket_id)
        self.check_object_permissions(request, ticket)

        serializer = TicketStatusChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        change_status = to_async(TicketService().change_status)
        updated = await change_status(
            ticket_id=ticket_id, new_status=serializer.validated_data["status"], actor=request.user
        )
        serialize = to_async(_serialize_detail_sync)
        data = await serialize(updated)
        return Response(data)


class TicketCloseView(LoopRegisteringMixin, AsyncAPIView):
    """Cierre exige nota de resolución (requisito explícito de Técnico)."""

    permission_classes = (permissions.IsAuthenticated, IsOwnerOrAssignedTechnicianOrAdmin)

    @extend_schema(
        summary="Cerrar ticket",
        description="Requiere nota de resolución no vacía. Solo válido desde estado RESUELTO.",
        request=TicketCloseSerializer,
        responses=TicketDetailSerializer,
    )
    async def post(self, request, ticket_id: int):
        get_ticket = to_async(_get_ticket_sync)
        ticket = await get_ticket(ticket_id)
        self.check_object_permissions(request, ticket)

        serializer = TicketCloseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        close_ticket = to_async(TicketService().close_ticket)
        updated = await close_ticket(
            ticket_id=ticket_id,
            resolution_notes=serializer.validated_data["resolution_notes"],
            actor=request.user,
        )
        serialize = to_async(_serialize_detail_sync)
        data = await serialize(updated)
        return Response(data)


class TicketCommentListCreateView(LoopRegisteringMixin, AsyncAPIView):
    permission_classes = (permissions.IsAuthenticated, IsOwnerOrAssignedTechnicianOrAdmin)

    @extend_schema(
        summary="Agregar comentario a ticket",
        request=TicketCommentCreateSerializer,
        responses={201: TicketCommentSerializer},
    )
    async def post(self, request, ticket_id: int):
        get_ticket = to_async(_get_ticket_sync)
        ticket = await get_ticket(ticket_id)
        self.check_object_permissions(request, ticket)

        serializer = TicketCommentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Defensa en profundidad: solo Técnico/Admin puede marcar una nota
        # como interna (en la práctica ya no hay otro rol logueado, ver
        # CustomTokenObtainPairSerializer, pero no se confía ciegamente
        # en el flag que mande el cliente).
        is_internal = serializer.validated_data["is_internal"]
        if is_internal and request.user.role not in (Role.TECNICO, Role.ADMIN):
            is_internal = False

        add_comment = to_async(TicketService().add_comment)
        comment = await add_comment(
            ticket_id=ticket_id, author=request.user,
            body=serializer.validated_data["body"], is_internal=is_internal,
        )
        return Response(TicketCommentSerializer(comment).data, status=status.HTTP_201_CREATED)


_ADMIN_ONLY_DETAIL = "Requiere rol Administrador."


def _is_admin(user) -> bool:
    return user.role == Role.ADMIN or user.is_superuser


class ResponseTemplateListCreateView(LoopRegisteringMixin, AsyncGenericAPIView):
    """CRUD de plantillas de respuesta — recurso simple sin lógica de
    negocio (no amerita Service+Repository), mismo patrón que
    accounts/api/views.py::RegisterView."""

    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = ResponseTemplateSerializer

    @extend_schema(summary="Listar plantillas de respuesta", responses=ResponseTemplateSerializer(many=True))
    async def get(self, request):
        list_templates = to_async(lambda: list(ResponseTemplate.objects.all()))
        templates = await list_templates()
        return Response(ResponseTemplateSerializer(templates, many=True).data)

    @extend_schema(
        summary="Crear plantilla de respuesta (solo Admin)",
        request=ResponseTemplateSerializer, responses={201: ResponseTemplateSerializer},
    )
    async def post(self, request):
        if not _is_admin(request.user):
            return Response({"detail": _ADMIN_ONLY_DETAIL}, status=status.HTTP_403_FORBIDDEN)

        def _create():
            serializer = ResponseTemplateSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            return serializer.save()

        template = await to_async(_create)()
        return Response(ResponseTemplateSerializer(template).data, status=status.HTTP_201_CREATED)


class ResponseTemplateDetailView(LoopRegisteringMixin, AsyncAPIView):
    permission_classes = (permissions.IsAuthenticated,)

    @extend_schema(summary="Detalle de plantilla de respuesta", responses=ResponseTemplateSerializer)
    async def get(self, request, template_id: int):
        get_template = to_async(lambda: ResponseTemplate.objects.get(pk=template_id))
        template = await get_template()
        return Response(ResponseTemplateSerializer(template).data)

    @extend_schema(
        summary="Editar plantilla de respuesta (solo Admin)",
        request=ResponseTemplateSerializer, responses=ResponseTemplateSerializer,
    )
    async def patch(self, request, template_id: int):
        if not _is_admin(request.user):
            return Response({"detail": _ADMIN_ONLY_DETAIL}, status=status.HTTP_403_FORBIDDEN)

        def _update():
            template = ResponseTemplate.objects.get(pk=template_id)
            serializer = ResponseTemplateSerializer(template, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            return serializer.save()

        updated = await to_async(_update)()
        return Response(ResponseTemplateSerializer(updated).data)

    @extend_schema(summary="Eliminar plantilla de respuesta (solo Admin)", responses={204: None})
    async def delete(self, request, template_id: int):
        if not _is_admin(request.user):
            return Response({"detail": _ADMIN_ONLY_DETAIL}, status=status.HTTP_403_FORBIDDEN)

        def _delete():
            ResponseTemplate.objects.filter(pk=template_id).delete()

        await to_async(_delete)()
        return Response(status=status.HTTP_204_NO_CONTENT)


class TicketTimeLogListCreateView(LoopRegisteringMixin, AsyncAPIView):
    """Solo Técnico registra tiempo trabajado (requisito explícito)."""

    permission_classes = (permissions.IsAuthenticated,)

    @extend_schema(
        summary="Registrar tiempo trabajado (solo Técnico asignado)",
        request=TicketTimeLogCreateSerializer,
        responses={201: TicketTimeLogSerializer},
    )
    async def post(self, request, ticket_id: int):
        serializer = TicketTimeLogCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        log_time = to_async(TicketService().log_time)
        log = await log_time(
            ticket_id=ticket_id, technician=request.user, **serializer.validated_data
        )
        return Response(TicketTimeLogSerializer(log).data, status=status.HTTP_201_CREATED)


class DashboardSummaryView(LoopRegisteringMixin, AsyncAPIView):
    """Dashboard ejecutivo: solo Admin (requisito explícito del rol).
    Agregaciones (Count/Avg) corren en threadpool vía sync_to_async,
    igual que el resto de vistas — el ORM sigue siendo sync."""

    permission_classes = (IsAdmin,)

    @extend_schema(
        summary="Dashboard ejecutivo (solo Admin)",
        description=(
            "KPIs agregados: conteo por estado/categoría, tiempo "
            "promedio de resolución, y tickets vencidos por SLA "
            "(umbral plano en settings.TICKET_SLA_HOURS)."
        ),
        responses=DashboardSummarySerializer,
    )
    async def get(self, request):
        get_summary = to_async(DashboardService().get_summary)
        summary = await get_summary()
        return Response(DashboardSummarySerializer(summary).data)
