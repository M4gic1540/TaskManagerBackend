"""Entrena el clasificador local de tickets (categoría) a partir del
dataset semilla sintético y, opcionalmente, tickets reales ya
categorizados por humanos en la BD. Reemplaza la clasificación vía
n8n + API de IA externa: todo corre local con scikit-learn ("old
school" ML, sin red ni dependencias externas).

No se llama directo en producción — lo invoca
`python manage.py train_ticket_classifier` (ver
tickets/management/commands/train_ticket_classifier.py), que se
encarga de juntar el CSV semilla con los tickets reales de la BD."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import joblib
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline

logger = logging.getLogger("ticketera")

SEED_CSV_PATH = Path(__file__).resolve().parent / "dataset" / "seed_tickets.csv"
MODEL_DIR = Path(__file__).resolve().parent / "model"
MODEL_PATH = MODEL_DIR / "ticket_classifier.joblib"


def _build_pipeline() -> Pipeline:
    return Pipeline([
        ("tfidf", TfidfVectorizer(
            ngram_range=(1, 2), strip_accents="unicode", lowercase=True, min_df=2,
        )),
        ("clf", LogisticRegression(max_iter=1000)),
    ])


@dataclass
class TrainingReport:
    category_accuracy: float
    n_samples: int


def _load_seed_rows() -> pd.DataFrame:
    return pd.read_csv(SEED_CSV_PATH)


def _texts(df: pd.DataFrame) -> pd.Series:
    return df["title"].fillna("") + ". " + df["description"].fillna("")


def _safe_test_size(y: pd.Series, fraction: float = 0.1) -> int:
    """train_test_split(stratify=...) exige al menos 1 muestra de cada
    clase en el split de test — con `fraction` fija (10%), un dataset
    chico (tests, por ejemplo) puede pedir menos filas de test que
    clases distintas y reventar. Se calcula un tamaño de test en
    cantidad absoluta que nunca baja de "una por clase"; con el
    dataset semilla real (~10k filas) esto no cambia nada (10% ya
    sobra de sobra para 8 categorías)."""
    n_classes = y.nunique()
    return max(round(len(y) * fraction), n_classes)


def train_and_save(
    extra_rows: list[dict] | None = None, *, seed_path: Path = SEED_CSV_PATH, model_path: Path = MODEL_PATH,
) -> TrainingReport:
    """Entrena el clasificador de categoría y guarda el artefacto joblib.

    `extra_rows` son tickets reales (dict con title/description/
    category) que se suman al dataset semilla — a medida que se
    acumulan tickets reales, reentrenar incluyéndolos mejora el modelo
    por sobre el dataset sintético puro."""
    seed_df = pd.read_csv(seed_path)
    if extra_rows:
        seed_df = pd.concat([seed_df, pd.DataFrame(extra_rows)], ignore_index=True)

    texts = _texts(seed_df)

    category_pipeline = _build_pipeline()
    X_train, X_test, y_train, y_test = train_test_split(
        texts, seed_df["category"], test_size=_safe_test_size(seed_df["category"]),
        random_state=42, stratify=seed_df["category"],
    )
    category_pipeline.fit(X_train, y_train)
    category_report = classification_report(y_test, category_pipeline.predict(X_test), output_dict=True, zero_division=0)

    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({
        "category_pipeline": category_pipeline,
        "n_samples": len(seed_df),
    }, model_path)

    logger.info(
        "Clasificador de tickets entrenado: %d filas, accuracy categoría=%.3f",
        len(seed_df), category_report["accuracy"],
    )
    return TrainingReport(
        category_accuracy=category_report["accuracy"],
        n_samples=len(seed_df),
    )
