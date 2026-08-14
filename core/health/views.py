"""Liveness: el proceso responde (no toca dependencias externas).
Readiness: el proceso puede atender tráfico real — corre los checks
registrados para este servicio (core/health/registry.py)."""
from __future__ import annotations

from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from core.health.registry import get_readiness_checks


class LivenessView(APIView):
    permission_classes = (AllowAny,)
    authentication_classes = ()

    def get(self, request):
        return Response({"status": "alive"})


class ReadinessView(APIView):
    permission_classes = (AllowAny,)
    authentication_classes = ()

    def get(self, request):
        checks = {}
        healthy = True
        for name, check_fn in get_readiness_checks().items():
            try:
                result = check_fn()
            except Exception as exc:  # noqa: BLE001 - un check roto no debe tumbar el endpoint
                result = {"ok": False, "detail": str(exc)}
            checks[name] = result
            if not result["ok"]:
                healthy = False

        return Response(
            {"status": "ready" if healthy else "not_ready", "checks": checks},
            status=200 if healthy else 503,
        )
