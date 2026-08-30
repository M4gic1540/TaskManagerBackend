"""Tests del clasificador local de tickets (tickets/ml/). Entrenan un
modelo chiquito en memoria sobre un puñado de ejemplos definidos acá
mismo -- no dependen del dataset semilla de ~10k filas ni de un
artefacto pre-entrenado, para que corran rápido y de forma
determinística (no son tests de la calidad del modelo real, sino de
que train_and_save()/TicketClassifier.predict() funcionan)."""
import pandas as pd
import pytest

from tickets.ml.classifier import TicketClassifier
from tickets.ml.train import train_and_save

# Cada categoría usada acá aparece al menos 2 veces: train_test_split
# (stratify=...) revienta si alguna clase tiene un solo miembro.
_TRAIN_ROWS = [
    {"title": "El computador no enciende", "description": "El computador no enciende desde esta mañana.", "category": "HARDWARE"},
    {"title": "La impresora no imprime nada", "description": "La impresora no responde hace días.", "category": "HARDWARE"},
    {"title": "El mouse falla a veces", "description": "El mouse falla de vez en cuando, no es grave.", "category": "HARDWARE"},
    {"title": "El teclado tiene una tecla suelta", "description": "Una tecla del teclado quedó suelta, puede esperar.", "category": "HARDWARE"},
    {"title": "El wifi no conecta", "description": "El wifi de la oficina no logra conectar.", "category": "RED"},
    {"title": "La red está muy lenta", "description": "La red del laboratorio está muy lenta hace rato.", "category": "RED"},
    {"title": "Internet caído en todo el piso", "description": "Internet caído en todo el piso, es crítico y afecta a todos.", "category": "RED"},
    {"title": "La red completa no funciona", "description": "La red completa no funciona, es una emergencia.", "category": "RED"},
    {"title": "Mi cuenta de correo quedó bloqueada", "description": "Mi cuenta de correo quedó bloqueada, no me deja entrar.", "category": "ACCESOS"},
    {"title": "Olvidé mi contraseña", "description": "Olvidé la contraseña de mi usuario y no puedo entrar.", "category": "ACCESOS"},
]


@pytest.fixture
def trained_model_path(tmp_path):
    seed_csv = tmp_path / "seed.csv"
    pd.DataFrame(_TRAIN_ROWS).to_csv(seed_csv, index=False)
    model_path = tmp_path / "model" / "ticket_classifier.joblib"

    train_and_save(seed_path=seed_csv, model_path=model_path)
    return model_path


class TestTrainAndSave:
    def test_writes_artifact_with_expected_accuracy_fields(self, tmp_path):
        seed_csv = tmp_path / "seed.csv"
        pd.DataFrame(_TRAIN_ROWS).to_csv(seed_csv, index=False)
        model_path = tmp_path / "model" / "ticket_classifier.joblib"

        report = train_and_save(seed_path=seed_csv, model_path=model_path)

        assert model_path.exists()
        assert report.n_samples == len(_TRAIN_ROWS)
        assert 0.0 <= report.category_accuracy <= 1.0

    def test_merges_extra_rows_with_seed(self, tmp_path):
        seed_csv = tmp_path / "seed.csv"
        pd.DataFrame(_TRAIN_ROWS).to_csv(seed_csv, index=False)
        model_path = tmp_path / "model" / "ticket_classifier.joblib"
        extra = [
            {"title": "El scanner no prende", "description": "El scanner no prende desde ayer.", "category": "HARDWARE"},
        ]

        report = train_and_save(extra_rows=extra, seed_path=seed_csv, model_path=model_path)

        assert report.n_samples == len(_TRAIN_ROWS) + 1


class TestTicketClassifierPredict:
    def test_predicts_category_with_confidence(self, trained_model_path):
        classifier = TicketClassifier(model_path=trained_model_path)

        result = classifier.predict(
            "El computador no enciende", "El computador no enciende desde esta mañana."
        )

        assert result is not None
        assert result.category in {"HARDWARE", "RED", "ACCESOS"}
        assert 0.0 <= result.category_confidence <= 1.0

    def test_returns_none_when_model_not_trained(self, tmp_path):
        classifier = TicketClassifier(model_path=tmp_path / "no-existe.joblib")

        assert classifier.predict("titulo", "descripción") is None

    def test_loads_artifact_only_once(self, trained_model_path, monkeypatch):
        """El artefacto se carga una sola vez por instancia (Singleton
        a nivel de proceso vía TicketClassifier.get()); acá se verifica
        el mecanismo de carga perezosa en sí, sin pasar por get()."""
        import tickets.ml.classifier as classifier_module

        calls = []
        original_load = classifier_module.joblib.load

        def _counting_load(path):
            calls.append(path)
            return original_load(path)

        monkeypatch.setattr(classifier_module.joblib, "load", _counting_load)

        classifier = TicketClassifier(model_path=trained_model_path)
        classifier.predict("a", "b")
        classifier.predict("c", "d")

        assert len(calls) == 1
