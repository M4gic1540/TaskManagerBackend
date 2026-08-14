"""Vistas async de Inventario, mismo patrón que tickets/api/views.py:
adrf para async, Service Layer hace todo el trabajo de negocio."""
from adrf.generics import GenericAPIView as AsyncGenericAPIView
from adrf.views import APIView as AsyncAPIView
from django.http import HttpResponse
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import permissions, status
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsAdmin, IsTechnician
from core.async_support.bridge import to_async
from core.async_support.mixins import LoopRegisteringMixin
from core.exceptions import DomainError, EntityNotFoundError, ValidationError
from core.specifications.base import AlwaysTrueSpecification
from inventory.api.serializers import (
    AssetCreateSerializer,
    AssetDetailSerializer,
    AssetListSerializer,
    AssetPublicSerializer,
    AssetUpdateSerializer,
    InventoryDashboardSummarySerializer,
)
from inventory.import_mapping import row_to_asset_fields
from inventory.import_parser import parse_uploaded_inventory_file
from inventory.services.asset_service import AssetService
from inventory.services.dashboard_service import InventoryDashboardService
from inventory.services.glpi_service import GLPIInventoryService

from inventory.specifications.asset_specs import (
    AssetByCategorySpec,
    AssetByStatusSpec,
    AssetSearchTextSpec,
)


def _build_filter_spec(query_params):
    spec = AlwaysTrueSpecification()
    if status_ := query_params.get("status"):
        spec = spec & AssetByStatusSpec(status_)
    if category := query_params.get("category"):
        spec = spec & AssetByCategorySpec(category)
    if search := query_params.get("search"):
        spec = spec & AssetSearchTextSpec(search)
    return spec


def _list_assets_sync(query_params):
    service = AssetService()
    spec = _build_filter_spec(query_params)
    return list(service.repository.list(spec))


def _serialize_detail_sync(asset) -> dict:
    """Serializa a dict plano DENTRO del thread sync (recorre
    `history` que es lazy), igual que tickets/api/views.py."""
    list(asset.history.all())
    return AssetDetailSerializer(asset).data


def _get_asset_sync(asset_id: int) -> dict:
    asset = AssetService().repository.get_by_id(asset_id)
    return _serialize_detail_sync(asset)


def _create_asset_sync(actor, **fields) -> dict:
    asset = AssetService().create_asset(actor=actor, **fields)
    return _serialize_detail_sync(asset)


def _update_asset_sync(asset_id: int, actor, **fields) -> dict:
    asset = AssetService().update_asset(asset_id=asset_id, actor=actor, **fields)
    return _serialize_detail_sync(asset)


def _regenerate_qr_sync(asset_id: int, actor) -> dict:
    asset = AssetService().regenerate_qr(asset_id=asset_id, actor=actor)
    return _serialize_detail_sync(asset)


def _get_public_asset_sync(public_uuid) -> dict:
    asset = AssetService().get_public_detail(public_uuid)
    return AssetPublicSerializer(asset).data


class AssetListCreateView(LoopRegisteringMixin, AsyncGenericAPIView):
    """Lectura/escritura de inventario: reservado a Admin/Técnico, ya que
    el detalle incluye precio de compra, N° de factura y notas internas
    que un usuario USUARIO (solicitante de tickets) no debe poder leer."""

    permission_classes = (IsAdmin | IsTechnician,)
    serializer_class = AssetListSerializer

    @extend_schema(
        summary="Listar activos de inventario",
        parameters=[
            OpenApiParameter("status", str, description="Filtrar por estado exacto"),
            OpenApiParameter("category", str, description="Filtrar por categoría exacta"),
            OpenApiParameter("search", str, description="Búsqueda en código/nombre/serial/ubicación"),
        ],
        responses=AssetListSerializer(many=True),
    )
    async def get(self, request):
        assets = await to_async(_list_assets_sync)(request.query_params)
        page = self.paginate_queryset(assets)
        serializer = AssetListSerializer(page, many=True)
        return self.get_paginated_response(serializer.data)

    @extend_schema(
        summary="Registrar activo (genera QR automáticamente)",
        request=AssetCreateSerializer,
        responses={201: AssetDetailSerializer},
    )
    async def post(self, request):
        serializer = AssetCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            data = await to_async(_create_asset_sync)(request.user, **serializer.validated_data)
        except DomainError as exc:
            return Response({"detail": exc.message}, status=status.HTTP_400_BAD_REQUEST)
        return Response(data, status=status.HTTP_201_CREATED)


class AssetDetailView(LoopRegisteringMixin, AsyncGenericAPIView):
    permission_classes = (IsAdmin | IsTechnician,)
    serializer_class = AssetDetailSerializer

    @extend_schema(summary="Detalle de activo (staff)", responses=AssetDetailSerializer)
    async def get(self, request, asset_id: int):
        try:
            data = await to_async(_get_asset_sync)(asset_id)
        except EntityNotFoundError as exc:
            return Response({"detail": exc.message}, status=status.HTTP_404_NOT_FOUND)
        return Response(data)

    @extend_schema(summary="Editar activo", request=AssetUpdateSerializer, responses=AssetDetailSerializer)
    async def patch(self, request, asset_id: int):
        serializer = AssetUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            data = await to_async(_update_asset_sync)(asset_id, request.user, **serializer.validated_data)
        except DomainError as exc:
            code = status.HTTP_404_NOT_FOUND if isinstance(exc, EntityNotFoundError) else status.HTTP_400_BAD_REQUEST
            return Response({"detail": exc.message}, status=code)
        return Response(data)

    @extend_schema(summary="Eliminar activo (solo Admin)")
    async def delete(self, request, asset_id: int):
        try:
            delete_asset = to_async(AssetService().delete_asset)
            await delete_asset(asset_id=asset_id, actor=request.user)
        except DomainError as exc:
            code = status.HTTP_404_NOT_FOUND if isinstance(exc, EntityNotFoundError) else status.HTTP_403_FORBIDDEN
            return Response({"detail": exc.message}, status=code)
        return Response(status=status.HTTP_204_NO_CONTENT)


class AssetRegenerateQRView(LoopRegisteringMixin, AsyncAPIView):
    permission_classes = (permissions.IsAuthenticated,)

    @extend_schema(summary="Regenerar imagen QR del activo", responses=AssetDetailSerializer)
    async def post(self, request, asset_id: int):
        try:
            data = await to_async(_regenerate_qr_sync)(asset_id, request.user)
        except DomainError as exc:
            code = status.HTTP_404_NOT_FOUND if isinstance(exc, EntityNotFoundError) else status.HTTP_403_FORBIDDEN
            return Response({"detail": exc.message}, status=code)
        return Response(data)


class AssetPublicDetailView(LoopRegisteringMixin, AsyncGenericAPIView):
    """Vista SIN autenticación: es lo que abre el navegador al escanear
    el QR físico pegado en el activo."""

    permission_classes = (permissions.AllowAny,)
    serializer_class = AssetPublicSerializer
    authentication_classes = []

    @extend_schema(summary="Detalle público de activo (vía QR)", responses=AssetPublicSerializer)
    async def get(self, request, public_uuid):
        try:
            data = await to_async(_get_public_asset_sync)(public_uuid)
        except EntityNotFoundError:
            return Response({"detail": "Activo no encontrado."}, status=status.HTTP_404_NOT_FOUND)
        return Response(data)


class AssetImportView(APIView):
    """Importa la planilla legacy (CSV o XLSX exportado del Excel de
    compras) y crea un Asset por fila, con su QR. Reemplaza el
    intermediario Excel/GLPI: de acá en adelante el inventario vive
    únicamente en esta plataforma.

    Vista SÍNCRONA (no adrf): procesar un archivo completo con decenas
    de filas no se beneficia de async, y así evitamos correr el parser
    de openpyxl dentro del bridge sync/async."""

    # openpyxl carga el workbook completo en memoria: sin este tope, un
    # archivo gigante (o un xlsx armado como zip bomb) permite agotar
    # memoria del proceso antes de que se valide una sola fila.
    MAX_IMPORT_FILE_SIZE = 10 * 1024 * 1024  # 10 MB

    permission_classes = (IsAdmin | IsTechnician,)
    parser_classes = (MultiPartParser,)

    @extend_schema(
        summary="Importar inventario legacy desde CSV/XLSX",
        description="Sube el Excel/CSV de compras. Cada fila se convierte en un Asset con QR. "
        "Filas ya importadas (mismo 'Serie GLPI') se omiten para permitir resubir el mismo archivo.",
    )
    def post(self, request):
        uploaded_file = request.FILES.get("file")
        if not uploaded_file:
            return Response({"detail": "Debes adjuntar un archivo en el campo 'file'."}, status=status.HTTP_400_BAD_REQUEST)

        if uploaded_file.size > self.MAX_IMPORT_FILE_SIZE:
            return Response(
                {"detail": f"El archivo supera el máximo permitido de {self.MAX_IMPORT_FILE_SIZE // (1024 * 1024)}MB."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            raw_rows = parse_uploaded_inventory_file(uploaded_file)
        except ValidationError as exc:
            return Response({"detail": exc.message}, status=status.HTTP_400_BAD_REQUEST)

        if not raw_rows:
            return Response({"detail": "El archivo no tiene filas de datos."}, status=status.HTTP_400_BAD_REQUEST)

        mapped_rows = [row_to_asset_fields(row) for row in raw_rows]

        try:
            result = AssetService().import_rows(rows=mapped_rows, actor=request.user)
        except DomainError as exc:
            return Response({"detail": exc.message}, status=status.HTTP_403_FORBIDDEN)

        return Response(result, status=status.HTTP_200_OK)


class AssetQRSheetView(APIView):
    """Genera una hoja Word (.docx) con los QR de varios activos, para
    imprimir y recortar como etiquetas físicas en una sola pasada.

    Vista SÍNCRONA (no adrf): armar el documento (dibujar cada QR en
    memoria + construir la tabla con python-docx) es CPU-bound y no se
    beneficia de async, mismo criterio que AssetImportView."""

    permission_classes = (permissions.IsAuthenticated,)

    @extend_schema(
        summary="Generar hoja Word con QR de varios activos",
        parameters=[
            OpenApiParameter(
                "ids",
                str,
                required=True,
                description="IDs de activos separados por coma, ej: 1,2,7,15",
            ),
        ],
    )
    def get(self, request):
        raw_ids = request.query_params.get("ids", "")
        try:
            asset_ids = [int(value) for value in raw_ids.split(",") if value.strip()]
        except ValueError:
            return Response(
                {"detail": "El parámetro 'ids' debe ser una lista de enteros separados por coma."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not asset_ids:
            return Response(
                {"detail": "Debes indicar al menos un id en 'ids'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            content = AssetService().generate_qr_sheet_docx(asset_ids=asset_ids)
        except DomainError as exc:
            return Response({"detail": exc.message}, status=status.HTTP_404_NOT_FOUND)

        response = HttpResponse(
            content,
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        response["Content-Disposition"] = 'attachment; filename="qr_activos.docx"'
        return response


class InventoryDashboardSummaryView(LoopRegisteringMixin, AsyncAPIView):
    """Dashboard ejecutivo de Inventario: solo Admin (mismo criterio de
    rol que el dashboard de tickets). Agregaciones corren en threadpool
    vía to_async, el ORM sigue siendo sync."""

    permission_classes = (IsAdmin,)

    @extend_schema(
        summary="Dashboard ejecutivo de inventario (solo Admin)",
        description=(
            "KPIs agregados: conteo por estado/categoría, disponibilidad, "
            "activos sin responsable asignado, top ubicaciones por cantidad "
            "de activos, y resumen de garantías vencidas/próximas a vencer "
            "(ventana configurada en settings.INVENTORY_WARRANTY_WARNING_DAYS)."
        ),
        responses=InventoryDashboardSummarySerializer,
    )
    async def get(self, request):
        get_summary = to_async(InventoryDashboardService().get_summary)
        summary = await get_summary()
        return Response(InventoryDashboardSummarySerializer(summary).data)


class GLPIAssetListView(LoopRegisteringMixin, AsyncAPIView):
    """Consulta directa a la base de datos MariaDB (GLPI) para visualizar el inventario real."""

    permission_classes = (permissions.IsAuthenticated,)

    @extend_schema(
        summary="Consultar inventario en tiempo real desde MariaDB (GLPI)",
        parameters=[
            OpenApiParameter("search", str, description="Búsqueda por texto en nombre/serial/ubicación/marca"),
            OpenApiParameter("category", str, description="Categoría (PC, MONITOR, IMPRESORA, RED, PERIFERICO, TELEFONO)"),
            OpenApiParameter("status", str, description="Filtro por estado"),
        ],
    )
    async def get(self, request):
        search = request.query_params.get("search")
        category = request.query_params.get("category")
        status_val = request.query_params.get("status")

        service = GLPIInventoryService()
        get_assets = to_async(service.list_assets)
        assets = await get_assets(search=search, category=category, status=status_val)
        return Response(assets)


class GLPIDashboardSummaryView(LoopRegisteringMixin, AsyncAPIView):
    """Resumen y KPIs agregados del inventario consultando MariaDB (GLPI)."""

    permission_classes = (permissions.IsAuthenticated,)

    @extend_schema(summary="Dashboard KPIs de inventario desde MariaDB (GLPI)")
    async def get(self, request):
        service = GLPIInventoryService()
        get_summary = to_async(service.get_dashboard_summary)
        summary = await get_summary()
        return Response(summary)


class GLPIQRImagesZipView(APIView):
    """Descarga un ZIP con imágenes PNG de QRs de activos GLPI (QR + S/N)."""

    permission_classes = (permissions.IsAuthenticated,)

    @extend_schema(
        summary="Descargar QRs como imágenes PNG en ZIP",
        parameters=[
            OpenApiParameter(
                "ids",
                str,
                required=True,
                description="IDs de activos GLPI separados por coma, ej: pc_123,monitor_45,periferico_10",
            ),
        ],
    )
    def get(self, request):
        raw_ids = request.query_params.get("ids", "")
        asset_ids = [value.strip() for value in raw_ids.split(",") if value.strip()]

        if not asset_ids:
            return Response(
                {"detail": "Debes indicar al menos un id en 'ids'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            service = GLPIInventoryService()
            content = service.generate_qr_images_zip(asset_ids=asset_ids)
        except DomainError as exc:
            return Response({"detail": exc.message}, status=status.HTTP_404_NOT_FOUND)

        response = HttpResponse(content, content_type="application/zip")
        response["Content-Disposition"] = 'attachment; filename="qr_glpi.zip"'
        return response


class AssetQRImagesZipView(APIView):
    """Descarga un ZIP con imágenes PNG de QRs de activos locales (QR + S/N)."""

    permission_classes = (permissions.IsAuthenticated,)

    @extend_schema(
        summary="Descargar QRs de activos locales como imágenes PNG en ZIP",
        parameters=[
            OpenApiParameter(
                "ids",
                str,
                required=True,
                description="IDs de activos separados por coma, ej: 1,2,7,15",
            ),
        ],
    )
    def get(self, request):
        raw_ids = request.query_params.get("ids", "")
        try:
            asset_ids = [int(value) for value in raw_ids.split(",") if value.strip()]
        except ValueError:
            return Response(
                {"detail": "El parámetro 'ids' debe ser una lista de enteros separados por coma."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not asset_ids:
            return Response(
                {"detail": "Debes indicar al menos un id en 'ids'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            service = AssetService()
            content = service.generate_qr_images_zip(asset_ids=asset_ids)
        except DomainError as exc:
            return Response({"detail": exc.message}, status=status.HTTP_404_NOT_FOUND)

        response = HttpResponse(content, content_type="application/zip")
        response["Content-Disposition"] = 'attachment; filename="qr_activos.zip"'
        return response

