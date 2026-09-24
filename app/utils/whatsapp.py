"""WhatsApp yönlendirme linki yardımcıları."""

from __future__ import annotations

from urllib.parse import quote

from app.utils.entities import EntityDict

DEFAULT_BUTTON_TEXT = "💬 WhatsApp'tan Yaz"
MAX_BUTTON_TEXT = 40
MAX_PREFILLED_MESSAGE = 200


def whatsapp_url(phone_digits: str, message: str | None = None) -> str:
    """https://wa.me/905551234567?text=... — basınca doğrudan WhatsApp sohbetini açar."""
    url = f"https://wa.me/{phone_digits}"
    if message:
        url += "?text=" + quote(message, safe="")
    return url


def utf16_len(text: str) -> int:
    """Telegram entity offset/length değerleri UTF-16 kod birimi cinsindendir."""
    return len(text.encode("utf-16-le")) // 2


def append_link(
    text: str, entities: list[EntityDict], label: str, url: str
) -> tuple[str, list[EntityDict]]:
    """Metnin sonuna tıklanabilir bir bağlantı satırı ekler (buton gönderilemediğinde yedek)."""
    prefix = f"{text}\n\n" if text.strip() else ""
    new_text = prefix + label
    link = {
        "type": "text_link",
        "offset": utf16_len(prefix),
        "length": utf16_len(label),
        "url": url,
    }
    return new_text, [*entities, link]
