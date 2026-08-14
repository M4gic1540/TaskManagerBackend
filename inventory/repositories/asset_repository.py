"""Repository concreto de Asset. Único punto que toca `Asset.objects`
directamente; Services siempre pasan por acá."""
from __future__ import annotations

from django.db.models import QuerySet

from core.exceptions import EntityNotFoundError
from core.repositories.base import DjangoRepository
from core.specifications.base import Specification
from inventory.models import Asset, AssetHistory


class AssetRepository(DjangoRepository[Asset]):
    model = Asset

    def get_queryset(self) -> QuerySet[Asset]:
        return super().get_queryset()

    def get_by_uuid(self, public_uuid) -> Asset:
        try:
            return self.get_queryset().get(public_uuid=public_uuid)
        except Asset.DoesNotExist as exc:
            raise EntityNotFoundError(f"Activo con uuid={public_uuid} no existe.") from exc

    def list(self, spec: Specification | None = None) -> QuerySet[Asset]:
        return super().list(spec)

    def add_history(self, asset: Asset, changed_by, action: str) -> AssetHistory:
        return AssetHistory.objects.create(
            asset=asset,
            changed_by_id=changed_by.id,
            changed_by_username=changed_by.username,
            action=action,
        )
