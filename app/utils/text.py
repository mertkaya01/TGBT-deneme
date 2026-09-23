"""Metin ayrıştırma ve biçimlendirme yardımcıları."""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TypeVar
from zoneinfo import ZoneInfo

T = TypeVar("T")

_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")
_SESSION_NAME_RE = re.compile(r"^[A-Za-z0-9_]{2,32}$")
_PRIVATE_POST_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?(?:t|telegram)\.me/c/(\d+)/(?:\d+/)?(\d+)/?(?:\?.*)?$",
    re.IGNORECASE,
)
_PUBLIC_POST_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?(?:t|telegram)\.me/(?:s/)?([A-Za-z][A-Za-z0-9_]{3,31})/"
    r"(?:\d+/)?(\d+)/?(?:\?.*)?$",
    re.IGNORECASE,
)
_USERNAME_RE = re.compile(
    r"^(?:@|(?:https?://)?(?:www\.)?(?:t|telegram)\.me/)([A-Za-z][A-Za-z0-9_]{3,31})/?$",
    re.IGNORECASE,
)
_INVITE_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?(?:t|telegram)\.me/(?:\+|joinchat/)([A-Za-z0-9_-]+)/?$",
    re.IGNORECASE,
)


def tr_lower(text: str) -> str:
    """Türkçe'ye uygun küçük harfe çevirme (I → ı, İ → i)."""
    return text.replace("I", "ı").replace("İ", "i").lower()


def is_valid_session_name(name: str) -> bool:
    return bool(_SESSION_NAME_RE.fullmatch(name))


def normalize_phone(text: str) -> str | None:
    """'+90 555 123 45 67', '0090…' gibi girdileri '+905551234567' biçimine getirir."""
    raw = re.sub(r"[\s\-().]", "", text.strip())
    if raw.startswith("00"):
        raw = "+" + raw[2:]
    if not raw.startswith("+"):
        return None
    digits = raw[1:]
    if not digits.isdigit() or not 8 <= len(digits) <= 15:
        return None
    return "+" + digits


def extract_code(text: str, expected_length: int | None = None) -> str | None:
    """'1 8 7 3 5', '18-735' gibi girdilerden sadece rakamları alır."""
    digits = "".join(ch for ch in text if ch.isdigit())
    if expected_length and len(digits) != expected_length:
        return None
    if not 4 <= len(digits) <= 8:
        return None
    return digits


def parse_delay_range(text: str, max_value: float = 3600) -> tuple[float, float]:
    """'0-5', '0 5', '11 23', '3' → (min, max) saniye. Geçersizse ValueError."""
    numbers = [float(n.replace(",", ".")) for n in _NUMBER_RE.findall(text)]
    if not numbers or len(numbers) > 2 or "-" in text.strip()[:1]:
        raise ValueError("invalid range")
    low, high = (numbers[0], numbers[0]) if len(numbers) == 1 else (numbers[0], numbers[1])
    if low > high:
        low, high = high, low
    if high > max_value:
        raise ValueError("too large")
    return low, high


def parse_int(text: str, minimum: int, maximum: int) -> int:
    value = text.strip()
    if not value.isdigit():
        raise ValueError("not a number")
    number = int(value)
    if not minimum <= number <= maximum:
        raise ValueError("out of range")
    return number


@dataclass(frozen=True, slots=True)
class PostLink:
    """t.me gönderi bağlantısı. peer: '@kullaniciadi' veya '-100…' kanal kimliği."""

    peer: str
    message_id: int


def parse_post_link(text: str) -> PostLink | None:
    value = text.strip()
    if match := _PRIVATE_POST_RE.match(value):
        return PostLink(peer=f"-100{match.group(1)}", message_id=int(match.group(2)))
    if match := _PUBLIC_POST_RE.match(value):
        return PostLink(peer=f"@{match.group(1)}", message_id=int(match.group(2)))
    return None


@dataclass(frozen=True, slots=True)
class ChatReference:
    """Kullanıcının elle girdiği sohbet: kimlik, kullanıcı adı veya davet linki."""

    chat_id: int | None = None
    username: str | None = None
    invite_hash: str | None = None


def parse_chat_reference(text: str) -> ChatReference | None:
    value = text.strip()
    if re.fullmatch(r"-?\d{5,20}", value):
        return ChatReference(chat_id=int(value))
    if match := _INVITE_RE.match(value):
        return ChatReference(invite_hash=match.group(1))
    if match := _USERNAME_RE.match(value):
        return ChatReference(username=match.group(1))
    return None


def split_keywords(text: str) -> list[str]:
    """'fiyat, ücret ,  kaç TL' → ['fiyat', 'ücret', 'kaç tl'] (normalize, tekrarsız)."""
    seen: dict[str, None] = {}
    for part in text.split(","):
        keyword = " ".join(tr_lower(part).split())
        if keyword:
            seen.setdefault(keyword, None)
    return list(seen)


def chunked(items: Sequence[T], size: int) -> Iterator[Sequence[T]]:
    if size < 1:
        raise ValueError("size must be >= 1")
    for start in range(0, len(items), size):
        yield items[start : start + size]


def shorten(text: str, limit: int = 60) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def format_duration(seconds: float) -> str:
    seconds = int(max(seconds, 0))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    parts = []
    if hours:
        parts.append(f"{hours} sa")
    if minutes:
        parts.append(f"{minutes} dk")
    if secs or not parts:
        parts.append(f"{secs} sn")
    return " ".join(parts)


def format_seconds_value(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def format_dt(value: datetime | None, tz: ZoneInfo) -> str:
    if value is None:
        return "—"
    return value.astimezone(tz).strftime("%d.%m %H:%M")


def keyword_matches(normalized_text: str, keyword: str, match_type: str) -> bool:
    """normalized_text ve keyword tr_lower ile normalize edilmiş olmalı."""
    if match_type == "exact":
        return " ".join(normalized_text.split()) == keyword
    if match_type == "word":
        return re.search(rf"(?<!\w){re.escape(keyword)}(?!\w)", normalized_text) is not None
    return keyword in normalized_text
