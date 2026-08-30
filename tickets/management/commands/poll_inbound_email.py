"""Ingesta de correo -> ticket: revisa periódicamente el buzón de
soporte (IMAP genérico — hoy un servidor propio, mañana Google
Workspace, sin cambiar código, solo INBOUND_EMAIL_HOST) y convierte
cada correo no leído en un ticket nuevo, o en una respuesta (comentario)
de un ticket existente si el asunto trae su código (`TCK-XXXXXXXX`).

Corre como un proceso de larga duración (servicio dedicado
`tickets-email-poller` en docker-compose.yml, mismo build que
`tickets`). Sin INBOUND_EMAIL_HOST configurado, se loguea y no hace
nada — mismo criterio que el resto de integraciones opcionales del
proyecto (vacío no rompe nada).

Uso:
    python manage.py poll_inbound_email
    python manage.py poll_inbound_email --once   # una sola pasada (tests/debug)
"""
from __future__ import annotations

import email
import html
import imaplib
import logging
import re
import time
from dataclasses import dataclass
from email.header import decode_header
from email.utils import parseaddr

from django.conf import settings
from django.core.management.base import BaseCommand

from core.exceptions import DomainError
from tickets.services.ticket_service import TicketService

logger = logging.getLogger("ticketera")

_TAG_RE = re.compile(r"<[^>]+>")
_BLOCK_TAG_RE = re.compile(r"<(br|p|div|li|tr)\b[^>]*>", re.IGNORECASE)
_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True)
class ParsedEmail:
    message_id: str
    sender_email: str
    sender_name: str
    subject: str
    body: str


def _safe_decode(payload: bytes, charset: str | None) -> str:
    """Como `_safe_decode(b"...", "unknown-8bit")`: un charset
    inexistente/no soportado por Python lanza `LookupError` ANTES de
    llegar a `errors="replace"` (que solo protege de bytes inválidos,
    no de un nombre de codificación desconocido). Es un charset legacy
    real y frecuente, no un caso exótico — sin este fallback, un correo
    así tumba el parseo completo."""
    try:
        return payload.decode(charset or "utf-8", errors="replace")
    except (LookupError, TypeError):
        return payload.decode("utf-8", errors="replace")


def _decode(value: str | None) -> str:
    if not value:
        return ""
    parts = decode_header(value)
    decoded = ""
    for text, charset in parts:
        if isinstance(text, bytes):
            decoded += _safe_decode(text, charset)
        else:
            decoded += text
    return decoded


def _html_to_text(raw_html: str) -> str:
    """Conversión best-effort de HTML a texto plano para correos que
    solo traen `text/html` (la mayoría de clientes webmail modernos:
    Gmail, Outlook web). No es un parser HTML completo — alcanza para
    no perder el contenido del correo, que es lo que importa acá."""
    without_scripts = _SCRIPT_STYLE_RE.sub("", raw_html)
    with_breaks = _BLOCK_TAG_RE.sub("\n", without_scripts)
    without_tags = _TAG_RE.sub("", with_breaks)
    return html.unescape(without_tags).strip()


def _extract_plain_body(msg: email.message.Message) -> str:
    if msg.is_multipart():
        html_part_text: str | None = None
        for part in msg.walk():
            if part.get_filename():
                continue
            content_type = part.get_content_type()
            if content_type == "text/plain":
                payload = part.get_payload(decode=True) or b""
                charset = part.get_content_charset() or "utf-8"
                return _safe_decode(payload, charset).strip()
            if content_type == "text/html" and html_part_text is None:
                payload = part.get_payload(decode=True) or b""
                charset = part.get_content_charset() or "utf-8"
                html_part_text = _safe_decode(payload, charset)
        # Sin parte text/plain: degradar a la parte text/html si existe,
        # en vez de devolver vacío (que hoy hace fallar create_ticket y
        # deja el correo sin marcar \Seen — reprocesado para siempre).
        return _html_to_text(html_part_text) if html_part_text else ""

    payload = msg.get_payload(decode=True) or b""
    charset = msg.get_content_charset() or "utf-8"
    text = _safe_decode(payload, charset).strip()
    if msg.get_content_type() == "text/html":
        text = _html_to_text(text)
    return text


def parse_message(raw_bytes: bytes) -> ParsedEmail:
    """Función pura (sin IMAP) — separada para poder testear el
    parseo sin un servidor real."""
    msg = email.message_from_bytes(raw_bytes)
    sender_name, sender_email = parseaddr(_decode(msg.get("From")))
    return ParsedEmail(
        message_id=(msg.get("Message-ID") or "").strip(),
        sender_email=sender_email.strip().lower(),
        sender_name=sender_name.strip(),
        subject=_decode(msg.get("Subject")).strip(),
        body=_extract_plain_body(msg),
    )


def process_message(parsed: ParsedEmail) -> None:
    if not parsed.message_id or not parsed.sender_email:
        logger.warning("Correo entrante sin Message-ID o remitente válido, se descarta.")
        return
    TicketService().create_ticket_from_email(
        external_message_id=parsed.message_id,
        sender_email=parsed.sender_email,
        sender_name=parsed.sender_name,
        subject=parsed.subject,
        body=parsed.body,
    )


def _poll_once() -> None:
    imap_cls = imaplib.IMAP4_SSL if settings.INBOUND_EMAIL_USE_SSL else imaplib.IMAP4
    connection = imap_cls(settings.INBOUND_EMAIL_HOST, settings.INBOUND_EMAIL_PORT)
    try:
        connection.login(settings.INBOUND_EMAIL_USER, settings.INBOUND_EMAIL_PASSWORD)
        connection.select(settings.INBOUND_EMAIL_FOLDER)

        status_, data = connection.search(None, "UNSEEN")
        if status_ != "OK":
            logger.warning("IMAP search UNSEEN falló: %s", status_)
            return

        for msg_num in data[0].split():
            try:
                status_, msg_data = connection.fetch(msg_num, "(RFC822)")
                if status_ != "OK" or not msg_data or not msg_data[0]:
                    continue
                raw_bytes = msg_data[0][1]
                parsed = parse_message(raw_bytes)
                try:
                    process_message(parsed)
                except DomainError:
                    # Correo sintácticamente válido pero rechazado por
                    # una regla de negocio (hoy no debería pasar nunca,
                    # ver los fallbacks de _extract_plain_body/título en
                    # ticket_service — pero si pasa, es un descarte
                    # DEFINITIVO: marcar \Seen igual que un mensaje sin
                    # remitente válido. La alternativa (dejarlo UNSEEN)
                    # reprocesa el mismo correo para siempre y bloquea
                    # el resto del buzón detrás de él.
                    logger.exception(
                        "Correo IMAP #%s rechazado por regla de negocio, se descarta "
                        "(no se reintentará).", msg_num,
                    )
                connection.store(msg_num, "+FLAGS", "\\Seen")
            except Exception:
                # Fallo transitorio (IMAP, red, bug inesperado): NO se
                # marca \Seen a propósito, para reintentar en el
                # próximo ciclo. Un correo mal formado no debe tumbar
                # el resto del batch ni el proceso de polling.
                logger.exception(
                    "No se pudo procesar el mensaje IMAP #%s (se reintentará).", msg_num,
                )
    finally:
        try:
            connection.close()
        except Exception:
            logger.debug("No se pudo cerrar la conexión IMAP limpiamente.", exc_info=True)
        try:
            connection.logout()
        except Exception:
            # No debe enmascarar una excepción real ocurrida antes
            # (ej. login fallido) con un error de logout sobre una
            # conexión que nunca llegó a autenticarse.
            logger.debug("No se pudo hacer logout IMAP limpiamente.", exc_info=True)


class Command(BaseCommand):
    help = "Ingesta de correo entrante: crea/actualiza tickets desde el buzón de soporte."

    def add_arguments(self, parser):
        parser.add_argument(
            "--once", action="store_true",
            help="Hacer una sola pasada y salir, en vez de correr en loop indefinido.",
        )

    def handle(self, *args, **options):
        if not settings.INBOUND_EMAIL_HOST:
            self.stdout.write(
                "INBOUND_EMAIL_HOST vacío — ingesta de correo desactivada, no hago nada."
            )
            return

        interval = settings.INBOUND_EMAIL_POLL_INTERVAL_SECONDS
        while True:
            try:
                _poll_once()
            except Exception:
                logger.exception("Fallo revisando el buzón de correo entrante.")
            if options["once"]:
                return
            time.sleep(interval)
