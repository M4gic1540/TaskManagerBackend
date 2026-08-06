# pyrefly: ignore [missing-import]
from django.urls import path

from inventory.api.views import (
    AssetDetailView,
    AssetImportView,
    AssetListCreateView,
    AssetPublicDetailView,
    AssetQRSheetView,
    AssetRegenerateQRView,
    GLPIAssetListView,
    GLPIDashboardSummaryView,
    InventoryDashboardSummaryView,
)

urlpatterns = [
    path("", AssetListCreateView.as_view(), name="asset-list-create"),
    path("glpi/", GLPIAssetListView.as_view(), name="asset-glpi-list"),
    path("glpi/summary/", GLPIDashboardSummaryView.as_view(), name="asset-glpi-summary"),
    path("import/", AssetImportView.as_view(), name="asset-import"),
    path("dashboard/", InventoryDashboardSummaryView.as_view(), name="asset-dashboard"),
    path("qr-sheet/", AssetQRSheetView.as_view(), name="asset-qr-sheet"),
    path("<int:asset_id>/", AssetDetailView.as_view(), name="asset-detail"),
    path("<int:asset_id>/regenerate-qr/", AssetRegenerateQRView.as_view(), name="asset-regenerate-qr"),
    path("public/<uuid:public_uuid>/", AssetPublicDetailView.as_view(), name="asset-public-detail"),
]

