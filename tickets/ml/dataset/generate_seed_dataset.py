"""Genera un dataset semilla sintético de tickets en español para
entrenar el clasificador local de categoría (ver tickets/ml/train.py).
Reemplaza a la integración con n8n + una API de IA externa: como no
hay acceso a esa API, el "old school ML" corre enteramente local con
scikit-learn, y necesita datos para aprender.

La base de tickets está vacía en desarrollo, así que este script arma
~10.000 ejemplos combinando vocabulario + plantillas por categoría, con
`random.seed` fijo para que el CSV resultante sea reproducible (correr
el script dos veces produce exactamente el mismo archivo).

Cada fila puede llevar una frase de urgencia/baja urgencia agregada al
final de la descripción — no afecta ninguna etiqueta (ya no se
clasifica prioridad), es solo variación de texto para que el
clasificador de categoría generalice mejor sobre redacciones distintas.

Uso:
    python3 tickets/ml/dataset/generate_seed_dataset.py
"""
from __future__ import annotations

import csv
import random
from pathlib import Path

SEED = 42
ROWS_PER_CATEGORY = 1250

CONTEXTOS = [
    "desde esta mañana",
    "desde ayer en la tarde",
    "hace ya una semana",
    "justo antes de una reunión importante",
    "después de la última actualización",
    "de un momento a otro",
    "cada vez que lo intento",
    "de forma intermitente durante el día",
    "desde que volvimos de la semana de vacaciones",
    "sin ningún cambio de mi parte",
]

# Frases opcionales de variación de texto (no afectan ninguna
# etiqueta) — le dan al clasificador de categoría ejemplos con y sin
# lenguaje de urgencia, para que no dependa de eso para categorizar.
FRASES_URGENCIA = [
    "Es urgente, no puedo seguir trabajando.",
    "Necesito que se resuelva hoy mismo si es posible.",
    "Tengo una entrega importante y esto me lo está impidiendo.",
    "Ya es el segundo día sin poder trabajar por esto.",
    "Por favor priorizar, me está atrasando bastante.",
    "Es crítico: afecta a todo el piso y nadie puede trabajar.",
    "Es una emergencia, no hay acceso a nada y somos varios equipos afectados.",
    "Sistema completo caído para todo el área, se necesita atención inmediata.",
    "Afecta a toda la oficina al mismo tiempo, no es solo mi puesto.",
]
FRASES_BAJA_URGENCIA = [
    "No es urgente, pueden revisarlo cuando tengan tiempo.",
    "No corre prisa, es solo para dejarlo registrado.",
    "Puede esperar, no me está bloqueando por ahora.",
    "Sin apuro, cualquier día de esta semana está bien.",
]

# --- Categorías con patrón "sujeto + síntoma" ------------------------------

SUBJECT_SYMPTOM_VOCAB = {
    "HARDWARE": {
        "subjects": [
            "el computador", "el notebook", "la impresora", "el monitor",
            "el teclado", "el mouse", "la webcam", "el proyector de la sala",
            "el scanner", "el disco duro externo", "la fuente de poder",
            "el cargador del notebook", "los parlantes", "el micrófono",
        ],
        "symptoms": [
            "no enciende", "no responde a nada", "se congela cada rato",
            "hace un ruido extraño al prender", "se reinicia solo",
            "no imprime nada aunque diga que está listo",
            "se ve la pantalla completamente negra",
            "no carga la batería aunque esté conectado",
            "se calienta demasiado y se apaga",
            "no reconoce el cable USB", "quedó con la pantalla azul",
            "perdió la conexión con el equipo", "no detecta el mouse ni el teclado",
        ],
    },
    "SOFTWARE": {
        "subjects": [
            "el sistema de gestión académica", "Outlook", "el navegador",
            "Excel", "el sistema de tickets", "la VPN institucional",
            "Zoom", "el antivirus", "Windows", "el sistema de facturación",
            "la aplicación de asistencia", "Teams", "el programa de nómina",
        ],
        "symptoms": [
            "se cierra solo apenas lo abro", "no abre de ninguna forma",
            "muestra un error al iniciar sesión",
            "quedó pegado cargando y no avanza",
            "no guarda los cambios que hago",
            "pide una licencia que no tengo activada",
            "se congela al abrir un archivo grande",
            "no reconoce mi usuario y contraseña",
            "aparece una pantalla de error en blanco",
            "dejó de sincronizar los archivos",
        ],
    },
    "RED": {
        "subjects": [
            "el wifi de la oficina", "la conexión a internet",
            "la red del piso 3", "el punto de red de mi oficina",
            "la VPN institucional", "la red del laboratorio",
            "la impresora de red", "el acceso a la carpeta compartida",
            "la red cableada de mi escritorio",
        ],
        "symptoms": [
            "está muy lenta desde hace rato", "se cae cada cierto tiempo",
            "no logra conectar", "aparece 'sin acceso a internet'",
            "no carga ninguna página", "se desconecta apenas me conecto",
            "no llega señal a mi oficina", "quedó completamente sin acceso",
        ],
    },
    "ACCESOS": {
        "subjects": [
            "mi cuenta de correo", "mi usuario del sistema",
            "mi clave de acceso", "mi cuenta de la VPN",
            "el acceso al edificio", "mi perfil en el sistema de tickets",
            "la cuenta de la impresora", "mi acceso a la carpeta compartida",
            "mi tarjeta de acceso",
        ],
        "symptoms": [
            "quedó bloqueada", "no me deja entrar de ninguna forma",
            "olvidé la contraseña y no puedo recuperarla",
            "dice que el usuario no existe", "necesito que me den acceso",
            "se venció y no puedo renovarla",
            "no tiene permisos para entrar a la carpeta",
            "pide verificación en dos pasos y el código nunca llega",
        ],
    },
    "RESERVA_DE_SALAS": {
        "subjects": [
            "la sala de reuniones", "la sala de videoconferencia",
            "el auditorio", "la sala de capacitación", "la sala 204",
            "el laboratorio de cómputo", "la sala de directorio",
        ],
        "symptoms": [
            "la necesito reservar para mañana",
            "quiero cancelar mi reserva de esta semana",
            "el sistema no me deja reservarla",
            "aparece ocupada pero en realidad está libre",
            "necesito cambiarle el horario a mi reserva",
            "quiero reservarla de forma recurrente todo el mes",
        ],
    },
}

# --- Categorías con frases completas (reclamo / sugerencia / otro) --------

FULL_PHRASE_VOCAB = {
    "RECLAMOS": [
        ("Técnico no llegó a la hora acordada",
         "El técnico no llegó a la hora que habíamos acordado para revisar el equipo."),
        ("Llevo dos semanas esperando respuesta",
         "Llevo dos semanas esperando una respuesta a mi ticket anterior y nadie me ha contactado."),
        ("El problema volvió a ocurrir",
         "El problema volvió a ocurrir después de que lo dieron por resuelto la semana pasada."),
        ("Me cerraron el ticket sin avisar",
         "Me cerraron el ticket anterior sin avisarme y el problema seguía sin solucionarse."),
        ("Atención muy demorosa",
         "La atención de la última vez fue muy demorosa, pasaron varios días sin novedades."),
        ("No me notificaron el cambio",
         "Cambiaron algo en el sistema y nadie del área nos avisó con anticipación."),
    ],
    "SUGERENCIAS": [
        ("Permitir adjuntar más de un archivo",
         "Sería bueno que el sistema de tickets permitiera adjuntar más de un archivo a la vez."),
        ("Recordatorio automático de reservas",
         "Propongo agregar un recordatorio automático antes de que empiece una reserva de sala."),
        ("Mejorar el buscador de tickets",
         "Sugiero mejorar el buscador del sistema de tickets, cuesta encontrar tickets antiguos."),
        ("App móvil para tickets",
         "Sería útil tener una aplicación móvil para revisar el estado de los tickets desde el celular."),
        ("Capacitación para personal nuevo",
         "Propongo capacitar al personal nuevo en el uso del sistema apenas ingresan."),
        ("Notificación por correo al cambiar estado",
         "Sería bueno recibir un correo automático cada vez que cambia el estado de mi ticket."),
    ],
    "OTRO": [
        ("Consulta general sobre un trámite",
         "Tengo una consulta general sobre cómo hacer un trámite, no encontré la información en la intranet."),
        ("Duda sobre a quién contactar",
         "No tengo claro a qué área debo escribir para este tema, quería que me orientaran."),
        ("Solicitud de información",
         "Necesito información sobre los horarios de atención de soporte técnico."),
        ("Consulta sobre políticas internas",
         "Tengo una duda sobre la política interna de uso de equipos, no encontré el documento."),
    ],
}


def _pick_extra_phrase(rng: random.Random) -> str | None:
    """Variación de texto pura (no afecta ninguna etiqueta): a veces
    agrega una frase de urgencia o de baja urgencia, a veces ninguna."""
    roll = rng.random()
    if roll < 0.55:
        return None
    if roll < 0.90:
        return rng.choice(FRASES_URGENCIA)
    return rng.choice(FRASES_BAJA_URGENCIA)


def _generate_subject_symptom_rows(category: str, n: int, rng: random.Random) -> list[dict]:
    vocab = SUBJECT_SYMPTOM_VOCAB[category]
    rows = []
    for _ in range(n):
        subject = rng.choice(vocab["subjects"])
        symptom = rng.choice(vocab["symptoms"])
        contexto = rng.choice(CONTEXTOS)
        extra = _pick_extra_phrase(rng)

        title = f"{subject.capitalize()} {symptom}"[:190]
        description = f"{subject.capitalize()} {symptom}, {contexto}."
        if extra:
            description = f"{description} {extra}"

        rows.append({"title": title, "description": description, "category": category})
    return rows


def _generate_full_phrase_rows(category: str, n: int, rng: random.Random) -> list[dict]:
    phrases = FULL_PHRASE_VOCAB[category]
    rows = []
    for _ in range(n):
        title, description = rng.choice(phrases)
        contexto = rng.choice(CONTEXTOS)
        extra = _pick_extra_phrase(rng)

        full_description = f"{description} Esto viene pasando {contexto}."
        if extra:
            full_description = f"{full_description} {extra}"

        rows.append({"title": title, "description": full_description, "category": category})
    return rows


def generate_dataset(rows_per_category: int = ROWS_PER_CATEGORY, seed: int = SEED) -> list[dict]:
    rng = random.Random(seed)
    rows: list[dict] = []
    for category in SUBJECT_SYMPTOM_VOCAB:
        rows.extend(_generate_subject_symptom_rows(category, rows_per_category, rng))
    for category in FULL_PHRASE_VOCAB:
        rows.extend(_generate_full_phrase_rows(category, rows_per_category, rng))
    rng.shuffle(rows)
    return rows


def main() -> None:
    rows = generate_dataset()
    out_path = Path(__file__).resolve().parent / "seed_tickets.csv"
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["title", "description", "category"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"Generados {len(rows)} tickets sintéticos en {out_path}")


if __name__ == "__main__":
    main()
