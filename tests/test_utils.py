from __future__ import annotations

import asyncio

import pytest
from aiogram.types import MessageEntity
from telethon.tl import types as tl

from app.utils.crypto import SessionCipher, SessionDecryptError
from app.utils.entities import (
    serialize_entities,
    telethon_to_dicts,
    to_aiogram_entities,
    to_telethon_entities,
)
from app.utils.flood import FloodGate
from app.utils.text import (
    chunked,
    extract_code,
    format_duration,
    is_valid_session_name,
    keyword_matches,
    normalize_phone,
    parse_chat_reference,
    parse_delay_range,
    parse_int,
    parse_post_link,
    split_keywords,
    tr_lower,
)

# --------------------------------------------------------------------------- metin


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0-5", (0, 5)),
        ("0 5", (0, 5)),
        ("11 23", (11, 23)),
        ("3", (3, 3)),
        ("5-0", (0, 5)),
        ("1,5 - 2.5", (1.5, 2.5)),
    ],
)
def test_parse_delay_range(raw, expected):
    assert parse_delay_range(raw) == expected


@pytest.mark.parametrize("raw", ["", "abc", "1 2 3", "-3", "0-99999"])
def test_parse_delay_range_invalid(raw):
    with pytest.raises(ValueError):
        parse_delay_range(raw)


def test_parse_int():
    assert parse_int(" 60 ", 1, 100) == 60
    for raw in ("0", "101", "6o", "-5"):
        with pytest.raises(ValueError):
            parse_int(raw, 1, 100)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+90 555 123 45 67", "+905551234567"),
        ("0090-555-123-4567", "+905551234567"),
        ("+44 7393 612345", "+447393612345"),
        ("5551234567", None),
        ("+90abc", None),
        ("+123", None),
    ],
)
def test_normalize_phone(raw, expected):
    assert normalize_phone(raw) == expected


def test_extract_code():
    assert extract_code("1 8 7 3 5", 5) == "18735"
    assert extract_code("18-735") == "18735"
    assert extract_code("1234", 5) is None
    assert extract_code("kod yok") is None


def test_session_name_rules():
    assert is_valid_session_name("Deneme")
    assert is_valid_session_name("dukkan_4")
    assert not is_valid_session_name("a")
    assert not is_valid_session_name("iki kelime")
    assert not is_valid_session_name("özel!")


@pytest.mark.parametrize(
    ("raw", "peer", "msg_id"),
    [
        ("https://t.me/kanalim/123", "@kanalim", 123),
        ("t.me/kanalim/123?single", "@kanalim", 123),
        ("https://t.me/s/kanalim/7", "@kanalim", 7),
        ("https://t.me/c/1234567890/55", "-1001234567890", 55),
        ("https://t.me/c/1234567890/3/55", "-1001234567890", 55),
    ],
)
def test_parse_post_link(raw, peer, msg_id):
    link = parse_post_link(raw)
    assert link is not None
    assert (link.peer, link.message_id) == (peer, msg_id)


def test_parse_post_link_rejects_plain_text():
    assert parse_post_link("merhaba https://t.me/kanalim/123") is None
    assert parse_post_link("https://t.me/kanalim") is None


def test_parse_chat_reference():
    assert parse_chat_reference("-1001234567890").chat_id == -1001234567890
    assert parse_chat_reference("@grubum").username == "grubum"
    assert parse_chat_reference("https://t.me/grubum").username == "grubum"
    assert parse_chat_reference("https://t.me/+AbC_123").invite_hash == "AbC_123"
    assert parse_chat_reference("??") is None


def test_turkish_lowercase_and_matching():
    assert tr_lower("FİYAT IŞIK") == "fiyat ışık"
    text = tr_lower("Bu ürünün FİYATI nedir?")
    assert keyword_matches(text, "fiyat", "contains")
    assert not keyword_matches(text, "fiyat", "word")
    assert keyword_matches(tr_lower("fiyat?"), "fiyat", "word")
    assert keyword_matches(tr_lower("  Fiyat  "), "fiyat", "exact")
    assert not keyword_matches(text, "fiyat", "exact")


def test_split_keywords():
    assert split_keywords("Fiyat, ÜCRET ,  kaç   TL,fiyat") == ["fiyat", "ücret", "kaç tl"]


def test_chunked_and_duration():
    assert [list(c) for c in chunked([1, 2, 3, 4, 5, 6, 7], 3)] == [[1, 2, 3], [4, 5, 6], [7]]
    assert format_duration(3725) == "1 sa 2 dk 5 sn"
    assert format_duration(0) == "0 sn"


# --------------------------------------------------------------------------- entity dönüşümü


def test_entity_roundtrip_keeps_formatting_and_custom_emoji():
    entities = [
        MessageEntity(type="bold", offset=0, length=4),
        MessageEntity(type="italic", offset=5, length=3),
        MessageEntity(type="pre", offset=9, length=4, language="python"),
        MessageEntity(type="text_link", offset=14, length=2, url="https://example.com"),
        MessageEntity(
            type="custom_emoji", offset=17, length=2, custom_emoji_id="5368324170671202286"
        ),
        MessageEntity(type="expandable_blockquote", offset=0, length=3),
        MessageEntity(type="url", offset=20, length=5),  # sunucu algılar, saklanmaz
    ]
    data = serialize_entities(entities)
    assert [d["type"] for d in data] == [
        "bold",
        "italic",
        "pre",
        "text_link",
        "custom_emoji",
        "expandable_blockquote",
    ]

    converted = to_telethon_entities(data)
    assert isinstance(converted[0], tl.MessageEntityBold)
    assert converted[2].language == "python"
    assert converted[3].url == "https://example.com"
    assert isinstance(converted[4], tl.MessageEntityCustomEmoji)
    assert converted[4].document_id == 5368324170671202286
    assert converted[5].collapsed is True
    assert (converted[4].offset, converted[4].length) == (17, 2)

    assert telethon_to_dicts(converted) == data
    assert [e.type for e in to_aiogram_entities(data)] == [d["type"] for d in data]


# --------------------------------------------------------------------------- şifreleme / flood


def test_cipher_roundtrip_and_wrong_key():
    key = SessionCipher.generate_key()
    token = SessionCipher(key).encrypt("gizli-oturum")
    assert SessionCipher(key).decrypt(token) == "gizli-oturum"
    with pytest.raises(SessionDecryptError):
        SessionCipher(SessionCipher.generate_key()).decrypt(token)
    with pytest.raises(ValueError):
        SessionCipher("gecersiz")


async def test_flood_gate_waits_for_penalty():
    now = [0.0]
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)
        now[0] += seconds

    gate = FloodGate(clock=lambda: now[0], sleep=fake_sleep)
    await gate.wait()
    assert slept == []
    gate.penalize(10)
    gate.penalize(3)  # daha kısa ceza mevcut süreyi kısaltmaz
    assert gate.remaining == 10
    await asyncio.wait_for(gate.wait(), 1)
    assert slept == [10]
    assert gate.remaining == 0


# --------------------------------------------------------------------------- WhatsApp


def test_whatsapp_url_and_link_fallback():
    from app.utils.whatsapp import append_link, whatsapp_url

    assert whatsapp_url("905551112233") == "https://wa.me/905551112233"
    assert (
        whatsapp_url("905551112233", "Merhaba, fiyat?")
        == "https://wa.me/905551112233?text=Merhaba%2C%20fiyat%3F"
    )
    # Metin yoksa link tek başına, varsa iki satır aşağıya eklenir; mevcut biçimlendirme korunur.
    assert append_link("", [], "Yaz", "https://x") == (
        "Yaz",
        [{"type": "text_link", "offset": 0, "length": 3, "url": "https://x"}],
    )
    bold = {"type": "bold", "offset": 0, "length": 2}
    text, entities = append_link("😊 Selam", [bold], "WA", "https://x")
    assert text == "😊 Selam\n\nWA"
    assert entities == [bold, {"type": "text_link", "offset": 10, "length": 2, "url": "https://x"}]
