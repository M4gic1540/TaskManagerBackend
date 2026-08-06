"""Excepciones de dominio. Mapeadas a HTTP en core/api/exception_handler.py"""


class DomainError(Exception):
    """Base de toda excepción de negocio."""
    default_message = "Error de dominio."

    def __init__(self, message: str | None = None):
        super().__init__(message or self.default_message)
        self.message = message or self.default_message


class EntityNotFoundError(DomainError):
    default_message = "Entidad no encontrada."


class PermissionDeniedError(DomainError):
    default_message = "No tiene permisos para esta operación."


class InvalidStateTransitionError(DomainError):
    default_message = "Transición de estado inválida."


class ValidationError(DomainError):
    default_message = "Datos inválidos."
