from __future__ import annotations

from django.db.models import Q

from core.specifications.base import Specification


class AssetByStatusSpec(Specification):
    def __init__(self, status: str):
        self.status = status

    def to_query(self) -> Q:
        return Q(status=self.status)


class AssetByCategorySpec(Specification):
    def __init__(self, category: str):
        self.category = category

    def to_query(self) -> Q:
        return Q(category=self.category)


class AssetSearchTextSpec(Specification):
    """Busca en código, nombre, serial y ubicación."""

    def __init__(self, text: str):
        self.text = text

    def to_query(self) -> Q:
        return (
            Q(code__icontains=self.text)
            | Q(name__icontains=self.text)
            | Q(serial_number__icontains=self.text)
            | Q(location__icontains=self.text)
            | Q(brand__icontains=self.text)
            | Q(model__icontains=self.text)
        )
