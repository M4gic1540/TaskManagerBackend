"""Specification Pattern sobre QuerySets de Django.

Cada Specification encapsula una regla de filtrado componible con
`&`, `|`, `~`. El Repository las traduce a `Q()` sin que el consumidor
conozca el esquema de la tabla.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from django.db.models import Q, QuerySet


class Specification(ABC):
    """Contrato: toda specification sabe construir su propio Q()."""

    @abstractmethod
    def to_query(self) -> Q:
        raise NotImplementedError

    def is_satisfied_by(self, queryset: QuerySet) -> QuerySet:
        return queryset.filter(self.to_query())

    def __and__(self, other: "Specification") -> "AndSpecification":
        return AndSpecification(self, other)

    def __or__(self, other: "Specification") -> "OrSpecification":
        return OrSpecification(self, other)

    def __invert__(self) -> "NotSpecification":
        return NotSpecification(self)


class AndSpecification(Specification):
    def __init__(self, left: Specification, right: Specification):
        self.left = left
        self.right = right

    def to_query(self) -> Q:
        return self.left.to_query() & self.right.to_query()


class OrSpecification(Specification):
    def __init__(self, left: Specification, right: Specification):
        self.left = left
        self.right = right

    def to_query(self) -> Q:
        return self.left.to_query() | self.right.to_query()


class NotSpecification(Specification):
    def __init__(self, spec: Specification):
        self.spec = spec

    def to_query(self) -> Q:
        return ~self.spec.to_query()


class AlwaysTrueSpecification(Specification):
    """Neutro para componer sin condicionales (`spec or AlwaysTrue()`)."""

    def to_query(self) -> Q:
        return Q()
