"""Observer Pattern: event bus desacoplado de Django signals.

Servicios publican eventos de dominio; observers (listeners) reaccionan
sin que el Service conozca sus efectos secundarios (notificaciones,
auditoría, KPIs). Cumple Open/Closed: agregar un observer nuevo no
modifica el Service emisor.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, ClassVar

from core.tracing.context import get_request_id

logger = logging.getLogger("ticketera.events")


@dataclass(frozen=True)
class DomainEvent:
    """Evento base inmutable. Subclases agregan payload propio."""

    occurred_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    request_id: str = field(default_factory=get_request_id)


class EventObserver(ABC):
    """Contrato que todo observer debe cumplir."""

    @abstractmethod
    def handle(self, event: DomainEvent) -> None:
        raise NotImplementedError


class EventBus:
    """Bus en memoria, proceso único (suficiente para monolito modular).

    Si el proyecto crece a microservicios, esta clase se reemplaza por
    un publisher a RabbitMQ/Kafka sin tocar los Services que la usan.
    """

    _subscribers: ClassVar[dict[type[DomainEvent], list[EventObserver]]] = (
        defaultdict(list)
    )

    @classmethod
    def subscribe(cls, event_type: type[DomainEvent], observer: EventObserver) -> None:
        cls._subscribers[event_type].append(observer)

    @classmethod
    def publish(cls, event: DomainEvent) -> None:
        for observer in cls._subscribers.get(type(event), []):
            try:
                observer.handle(event)
            except Exception:
                # Un observer roto no debe tumbar la transacción principal.
                logger.exception(
                    "Observer %s falló procesando %s",
                    observer.__class__.__name__,
                    type(event).__name__,
                )

    @classmethod
    def reset(cls) -> None:
        """Solo para tests: limpia subscripciones."""
        cls._subscribers.clear()


def event_handler(*event_types: type[DomainEvent]):
    """Decorator para registrar funciones simples como observers."""

    def decorator(func):
        class _FnObserver(EventObserver):
            def handle(self, event: DomainEvent) -> None:
                func(event)

        instance = _FnObserver()
        for et in event_types:
            EventBus.subscribe(et, instance)
        return func

    return decorator
