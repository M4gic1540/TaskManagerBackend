"""Repository Pattern: abstrae acceso a datos del Service Layer.

Los Services dependen de esta interfaz, no de `Model.objects` directo.
Esto permite testear Services con un FakeRepository en memoria (sin DB)
y sustituir el ORM sin tocar lógica de negocio.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from django.db.models import Model, QuerySet

from core.exceptions import EntityNotFoundError
from core.specifications.base import Specification

ModelT = TypeVar("ModelT", bound=Model)


class AbstractRepository(ABC, Generic[ModelT]):
    """Contrato mínimo que todo repositorio concreto implementa."""

    @abstractmethod
    def get_by_id(self, entity_id: int) -> ModelT: ...

    @abstractmethod
    def list(self, spec: Specification | None = None) -> QuerySet[ModelT]: ...

    @abstractmethod
    def create(self, **fields) -> ModelT: ...

    @abstractmethod
    def update(self, entity: ModelT, **fields) -> ModelT: ...

    @abstractmethod
    def delete(self, entity: ModelT) -> None: ...


class DjangoRepository(AbstractRepository[ModelT]):
    """Implementación base sobre el ORM de Django.

    Repos concretos (TicketRepository, UserRepository) heredan y solo
    definen `model` + queries específicas de su dominio.
    """

    model: type[ModelT]

    def get_queryset(self) -> QuerySet[ModelT]:
        return self.model.objects.all()

    def get_by_id(self, entity_id: int) -> ModelT:
        try:
            return self.get_queryset().get(pk=entity_id)
        except self.model.DoesNotExist as exc:
            raise EntityNotFoundError(
                f"{self.model.__name__} con id={entity_id} no existe."
            ) from exc

    def list(self, spec: Specification | None = None) -> QuerySet[ModelT]:
        qs = self.get_queryset()
        if spec is not None:
            qs = spec.is_satisfied_by(qs)
        return qs

    def create(self, **fields) -> ModelT:
        return self.model.objects.create(**fields)

    def update(self, entity: ModelT, **fields) -> ModelT:
        for key, value in fields.items():
            setattr(entity, key, value)
        entity.save(update_fields=list(fields.keys()))
        return entity

    def delete(self, entity: ModelT) -> None:
        entity.delete()
