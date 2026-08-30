"""Clasificador local de tickets: envoltorio delgado sobre el
artefacto entrenado por tickets/ml/train.py. Reemplaza la
clasificación vía n8n + API de IA externa — corre en el mismo proceso,
sin red ni secretos compartidos.

Si el artefacto todavía no existe (nadie corrió
`python manage.py train_ticket_classifier`), `predict()` devuelve
`None`: mismo criterio de "no-op seguro" que tenía el webhook de n8n
cuando N8N_TICKET_WEBHOOK_URL venía vacío — nunca bloquea ni rompe la
creación de un ticket."""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path

import joblib

logger = logging.getLogger("ticketera")

DEFAULT_MODEL_PATH = Path(__file__).resolve().parent / "model" / "ticket_classifier.joblib"


@dataclass(frozen=True)
class ClassificationResult:
    category: str
    category_confidence: float


class TicketClassifier:
    """Carga el artefacto una sola vez por proceso. `get()` entrega un
    singleton a nivel de módulo; protegido con lock por si dos
    requests concurrentes disparan la primera carga al mismo tiempo."""

    _instance: "TicketClassifier | None" = None
    _instance_lock = threading.Lock()

    def __init__(self, model_path: Path = DEFAULT_MODEL_PATH):
        self._model_path = model_path
        self._category_pipeline = None
        self._loaded = False
        self._load_lock = threading.Lock()

    @classmethod
    def get(cls) -> "TicketClassifier":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def _ensure_loaded(self) -> bool:
        if self._loaded:
            return self._category_pipeline is not None
        with self._load_lock:
            if self._loaded:
                return self._category_pipeline is not None
            if not self._model_path.exists():
                logger.info(
                    "Clasificador de tickets sin entrenar todavía (%s no existe) — "
                    "correr `python manage.py train_ticket_classifier`.",
                    self._model_path,
                )
                self._loaded = True
                return False
            # joblib.load usa pickle internamente, pero el artefacto es
            # generado y firmado por nuestro propio tickets/ml/train.py
            # en el mismo build/entrypoint — nunca una fuente externa o
            # subida por un usuario, así que la carga es de confianza.
            artifact = joblib.load(self._model_path)
            self._category_pipeline = artifact["category_pipeline"]
            self._loaded = True
            return True

    def predict(self, title: str, description: str) -> ClassificationResult | None:
        """Devuelve la categoría sugerida + confianza, o `None` si el
        modelo todavía no está entrenado."""
        if not self._ensure_loaded():
            return None
        text = f"{title or ''}. {description or ''}"

        category_proba = self._category_pipeline.predict_proba([text])[0]
        category_idx = category_proba.argmax()
        category = self._category_pipeline.classes_[category_idx]

        return ClassificationResult(
            category=str(category), category_confidence=float(category_proba[category_idx]),
        )
