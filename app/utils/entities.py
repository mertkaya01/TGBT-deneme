"""Biçimlendirme (entity) dönüşümleri.

Controller bot'a gelen mesajın biçimlendirmesi (kalın, italik, kod, özel emoji…) Bot API
``MessageEntity`` listesi olarak JSON'a kaydedilir. Userbot gönderirken bu liste Telethon'un
``MessageEntity*`` tiplerine çevrilir. İki API de offset/length değerlerini UTF-16 kod birimi
cinsinden tuttuğu için değerler birebir aktarılır.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from aiogram.types import MessageEntity
from telethon.tl import types as tl

EntityDict = dict[str, Any]

# Sunucunun kendisinin algıladığı türler (url, mention, hashtag…) saklanmaz.
_SIMPLE: dict[str, Callable[[int, int], Any]] = {
    "bold": tl.MessageEntityBold,
    "italic": tl.MessageEntityItalic,
    "underline": tl.MessageEntityUnderline,
    "strikethrough": tl.MessageEntityStrike,
    "spoiler": tl.MessageEntitySpoiler,
    "code": tl.MessageEntityCode,
}
SUPPORTED_TYPES = frozenset(
    {*_SIMPLE, "pre", "text_link", "custom_emoji", "blockquote", "expandable_blockquote"}
)


def serialize_entities(entities: Iterable[MessageEntity] | None) -> list[EntityDict]:
    """aiogram entity listesini JSON'a uygun sözlük listesine çevirir."""
    result: list[EntityDict] = []
    for entity in entities or ():
        if entity.type not in SUPPORTED_TYPES:
            continue
        item: EntityDict = {
            "type": entity.type,
            "offset": entity.offset,
            "length": entity.length,
        }
        if entity.url:
            item["url"] = entity.url
        if entity.language:
            item["language"] = entity.language
        if entity.custom_emoji_id:
            item["custom_emoji_id"] = entity.custom_emoji_id
        result.append(item)
    return result


def to_telethon_entities(data: Iterable[EntityDict] | None) -> list[Any]:
    """Kaydedilmiş sözlükleri Telethon ``formatting_entities`` listesine çevirir."""
    result: list[Any] = []
    for item in data or ():
        kind = item.get("type")
        offset, length = int(item["offset"]), int(item["length"])
        if kind in _SIMPLE:
            result.append(_SIMPLE[kind](offset, length))
        elif kind == "pre":
            result.append(tl.MessageEntityPre(offset, length, item.get("language") or ""))
        elif kind == "text_link" and item.get("url"):
            result.append(tl.MessageEntityTextUrl(offset, length, item["url"]))
        elif kind == "custom_emoji" and item.get("custom_emoji_id"):
            result.append(tl.MessageEntityCustomEmoji(offset, length, int(item["custom_emoji_id"])))
        elif kind == "blockquote":
            result.append(tl.MessageEntityBlockquote(offset, length))
        elif kind == "expandable_blockquote":
            result.append(tl.MessageEntityBlockquote(offset, length, collapsed=True))
    return result


def to_aiogram_entities(data: Iterable[EntityDict] | None) -> list[MessageEntity]:
    """Önizleme için kaydedilmiş sözlükleri tekrar aiogram entity'lerine çevirir."""
    return [MessageEntity(**item) for item in data or () if item.get("type") in SUPPORTED_TYPES]


def telethon_to_dicts(entities: Iterable[Any] | None) -> list[EntityDict]:
    """Telethon entity'lerini (ör. kaynak kanal mesajı) kayıt biçimine çevirir."""
    reverse = {cls: name for name, cls in _SIMPLE.items()}
    result: list[EntityDict] = []
    for entity in entities or ():
        base = {"offset": entity.offset, "length": entity.length}
        if type(entity) in reverse:
            result.append({"type": reverse[type(entity)], **base})
        elif isinstance(entity, tl.MessageEntityPre):
            result.append({"type": "pre", "language": entity.language or None, **base})
        elif isinstance(entity, tl.MessageEntityTextUrl):
            result.append({"type": "text_link", "url": entity.url, **base})
        elif isinstance(entity, tl.MessageEntityCustomEmoji):
            result.append(
                {"type": "custom_emoji", "custom_emoji_id": str(entity.document_id), **base}
            )
        elif isinstance(entity, tl.MessageEntityBlockquote):
            kind = "expandable_blockquote" if entity.collapsed else "blockquote"
            result.append({"type": kind, **base})
    return [{k: v for k, v in item.items() if v is not None} for item in result]
