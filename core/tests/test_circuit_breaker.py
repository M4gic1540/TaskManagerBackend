"""Tests del circuit breaker de GLPI: fallas reales (OperationalError)
se traducen a GLPIUnavailableError, y tras abrirse el circuito, las
llamadas siguientes fallan rápido sin invocar la función real."""
from unittest.mock import Mock

import pytest
from django.db.utils import OperationalError

from core.exceptions import DomainError
from core.resilience.circuit_breaker import GLPIUnavailableError, call_with_breaker, glpi_breaker


@pytest.fixture(autouse=True)
def _reset_breaker():
    glpi_breaker.close()
    yield
    glpi_breaker.close()


class TestGLPICircuitBreaker:
    def test_successful_call_passes_through(self):
        fn = Mock(return_value="ok")
        assert call_with_breaker(fn, 1, key="value") == "ok"
        fn.assert_called_once_with(1, key="value")

    def test_glpi_unavailable_is_a_domain_error(self):
        assert issubclass(GLPIUnavailableError, DomainError)

    def test_operational_error_is_translated_to_domain_error(self):
        fn = Mock(side_effect=OperationalError("conexión rechazada"))
        with pytest.raises(GLPIUnavailableError):
            call_with_breaker(fn)

    def test_opens_after_repeated_failures_and_then_fails_fast(self):
        failing_fn = Mock(side_effect=OperationalError("glpi caído"))

        for _ in range(glpi_breaker.fail_max + 1):
            with pytest.raises(GLPIUnavailableError):
                call_with_breaker(failing_fn)

        assert glpi_breaker.current_state == "open"

        # Circuito abierto: la siguiente llamada debe fallar rápido, SIN
        # invocar la función real (evita seguir golpeando una BD caída).
        failing_fn.reset_mock()
        with pytest.raises(GLPIUnavailableError):
            call_with_breaker(failing_fn)
        failing_fn.assert_not_called()
