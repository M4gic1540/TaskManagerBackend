"""Tests del parseo puro de correo entrante (sin IMAP real, ver
tickets/management/commands/poll_inbound_email.py). `parse_message`/
`process_message` están separados de `_poll_once` justamente para
poder testear esta lógica sin un servidor IMAP."""
from email.message import EmailMessage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import pytest

from tickets.management.commands.poll_inbound_email import parse_message, process_message
from tickets.models import Ticket


def _raw_email(*, message_id, from_addr, subject, body) -> bytes:
    msg = EmailMessage()
    msg["Message-ID"] = message_id
    msg["From"] = from_addr
    msg["Subject"] = subject
    msg["To"] = "sistemas@cmm.uchile.cl"
    msg.set_content(body)
    return bytes(msg)


def _raw_html_only_email(*, message_id, from_addr, subject, html_body) -> bytes:
    """Simula un cliente que solo manda `text/html` (webmail moderno:
    Gmail, Outlook), sin parte `text/plain` — el caso que antes dejaba
    `_extract_plain_body` devolver `""`."""
    msg = MIMEMultipart("alternative")
    msg["Message-ID"] = message_id
    msg["From"] = from_addr
    msg["Subject"] = subject
    msg["To"] = "sistemas@cmm.uchile.cl"
    msg.attach(MIMEText(html_body, "html"))
    return msg.as_bytes()


def _raw_email_with_bad_subject_charset(*, message_id, from_addr, body) -> bytes:
    """Un asunto codificado con un charset legacy que Python no
    reconoce (`unknown-8bit`) — frecuente en correo corporativo viejo,
    no un caso exótico."""
    raw = (
        f"Message-ID: {message_id}\r\n"
        f"From: {from_addr}\r\n"
        "Subject: =?unknown-8bit?Q?Impresi=F3n?=\r\n"
        "To: sistemas@cmm.uchile.cl\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "\r\n"
        f"{body}\r\n"
    )
    return raw.encode("utf-8")


class TestParseMessage:
    def test_extracts_sender_subject_and_body(self):
        raw = _raw_email(
            message_id="<abc123@correo.cmm.uchile.cl>",
            from_addr="Pedro Pérez <pedro.perez@uchile.cl>",
            subject="No me funciona el wifi",
            body="Desde esta mañana no logro conectarme a la red del piso 3.\n",
        )

        parsed = parse_message(raw)

        assert parsed.message_id == "<abc123@correo.cmm.uchile.cl>"
        assert parsed.sender_email == "pedro.perez@uchile.cl"
        assert parsed.sender_name == "Pedro Pérez"
        assert parsed.subject == "No me funciona el wifi"
        assert "Desde esta mañana" in parsed.body

    def test_sender_without_display_name(self):
        raw = _raw_email(
            message_id="<x@correo.cmm.uchile.cl>", from_addr="ana@uchile.cl",
            subject="Consulta", body="Cuerpo del correo.",
        )

        parsed = parse_message(raw)

        assert parsed.sender_email == "ana@uchile.cl"
        assert parsed.sender_name == ""

    def test_html_only_email_falls_back_to_extracted_text(self):
        """Regresión: antes `_extract_plain_body` devolvía `""` para un
        correo sin parte text/plain, lo que hacía fallar create_ticket
        y dejaba el mensaje sin marcar \\Seen (reprocesado para
        siempre). Ahora debe degradar el HTML a texto plano."""
        raw = _raw_html_only_email(
            message_id="<html@correo.cmm.uchile.cl>", from_addr="ana@uchile.cl",
            subject="No anda la impresora",
            html_body="<p>La impresora del piso 2 <b>no imprime</b>.</p><p>Urgente.</p>",
        )

        parsed = parse_message(raw)

        assert "no imprime" in parsed.body
        assert "Urgente" in parsed.body
        assert "<p>" not in parsed.body
        assert "<b>" not in parsed.body

    def test_invalid_header_charset_does_not_crash_parsing(self):
        """Regresión: un charset de header desconocido (`unknown-8bit`,
        común en correo legacy) lanzaba LookupError antes de llegar a
        errors="replace", tumbando el parseo completo del mensaje."""
        raw = _raw_email_with_bad_subject_charset(
            message_id="<charset@correo.cmm.uchile.cl>", from_addr="ana@uchile.cl",
            body="Cuerpo normal.",
        )

        parsed = parse_message(raw)  # no debe lanzar

        assert parsed.sender_email == "ana@uchile.cl"
        assert parsed.body == "Cuerpo normal."


@pytest.mark.django_db
class TestProcessMessage:
    def test_creates_ticket_from_new_message(self):
        raw = _raw_email(
            message_id="<nuevo@correo.cmm.uchile.cl>", from_addr="Pedro Pérez <pedro@uchile.cl>",
            subject="El proyector no enciende", body="El proyector de la sala 5 no enciende.",
        )

        process_message(parse_message(raw))

        ticket = Ticket.objects.get(external_message_id="<nuevo@correo.cmm.uchile.cl>")
        assert ticket.title == "El proyector no enciende"
        assert ticket.requester_email == "pedro@uchile.cl"

    def test_reply_to_known_ticket_adds_comment_instead_of_new_ticket(self):
        raw_original = _raw_email(
            message_id="<original@correo.cmm.uchile.cl>", from_addr="Pedro Pérez <pedro@uchile.cl>",
            subject="El proyector no enciende", body="El proyector de la sala 5 no enciende.",
        )
        process_message(parse_message(raw_original))
        ticket = Ticket.objects.get(external_message_id="<original@correo.cmm.uchile.cl>")

        raw_reply = _raw_email(
            message_id="<reply@correo.cmm.uchile.cl>", from_addr="Pedro Pérez <pedro@uchile.cl>",
            subject=f"Re: [{ticket.code}] El proyector no enciende",
            body="¿Alguna novedad con esto?",
        )
        process_message(parse_message(raw_reply))

        assert Ticket.objects.count() == 1
        ticket.refresh_from_db()
        assert ticket.comments.count() == 1
        assert ticket.comments.first().body == "¿Alguna novedad con esto?"

    def test_discards_message_without_valid_sender(self):
        raw = _raw_email(
            message_id="<sin-remitente@correo.cmm.uchile.cl>", from_addr="",
            subject="Asunto", body="Cuerpo.",
        )

        process_message(parse_message(raw))

        assert not Ticket.objects.filter(
            external_message_id="<sin-remitente@correo.cmm.uchile.cl>"
        ).exists()
