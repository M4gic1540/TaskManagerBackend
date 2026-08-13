"""Construcción de la imagen de etiqueta QR (QR + S/N + Nº INV) compartida
entre `AssetService` (activos locales) y `GLPIService` (activos GLPI), para
no duplicar la lógica de dibujo en los dos servicios."""
from __future__ import annotations

import io
import re

import qrcode
from PIL import Image, ImageDraw, ImageFont

QR_SIZE = 220
FONT_SIZE = 18
PADDING = 16
LINE_SPACING = 6


def load_label_font(size: int = FONT_SIZE):
    """Carga una fuente disponible del sistema."""
    font_candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for path in font_candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def build_qr_label_image(
    *,
    target_url: str,
    serial_number: str = "",
    inventory_number: str | None = None,
) -> io.BytesIO:
    """Construye una imagen PNG con el QR y, debajo, el S/N y el Nº de
    inventario (si existe). El canvas se dimensiona en base al texto real
    para que nunca quede cortado, sin importar cuán largo sea."""
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=2,
        border=1,
    )
    qr.add_data(target_url)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    qr_img = qr_img.resize((QR_SIZE, QR_SIZE), Image.Resampling.LANCZOS)

    lines = []
    serial_text = (serial_number or "").strip()
    if serial_text:
        lines.append(serial_text)
    inventory_text = (inventory_number or "").strip()
    if inventory_text:
        lines.append(f"Nº INV: {inventory_text}")
    if not lines:
        lines = ["SIN S/N"]

    font = load_label_font()
    probe_draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    line_sizes = []
    for line in lines:
        bbox = probe_draw.textbbox((0, 0), line, font=font)
        line_sizes.append((bbox[2] - bbox[0], bbox[3] - bbox[1]))

    max_text_width = max(width for width, _ in line_sizes)
    text_block_height = sum(height for _, height in line_sizes) + LINE_SPACING * (len(lines) - 1)

    canvas_width = max(QR_SIZE, max_text_width) + PADDING * 2
    canvas_height = QR_SIZE + PADDING + text_block_height + PADDING

    canvas = Image.new("RGB", (canvas_width, canvas_height), "white")
    canvas.paste(qr_img, ((canvas_width - QR_SIZE) // 2, 0))

    draw = ImageDraw.Draw(canvas)
    y = QR_SIZE + PADDING
    for line, (width, height) in zip(lines, line_sizes):
        x = (canvas_width - width) // 2
        draw.text((x, y), line, fill="black", font=font)
        y += height + LINE_SPACING

    buffer = io.BytesIO()
    canvas.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


def sanitize_filename(value: str) -> str:
    """Sanitiza el nombre de archivo."""
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return safe or "sin_sn"
