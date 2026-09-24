"""Userbot üzerinden içerik gönderimi: metin, fotoğraf, forward ve kişi kartı."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from telethon import errors
from telethon.tl import types as tl

from app.database.models import AutoMessageConfig, ContentType, DMAutoReplyConfig
from app.userbots.errors import ErrorAction, classify, wait_seconds
from app.utils.entities import EntityDict, to_telethon_entities
from app.utils.whatsapp import append_link

if TYPE_CHECKING:
    from telethon import TelegramClient

log = logging.getLogger(__name__)

_MEDIA_ERRORS = (
    errors.ChatSendMediaForbiddenError,
    errors.ChatSendPhotosForbiddenError,
    errors.ChatForwardsRestrictedError,
    errors.ChatSendGifsForbiddenError,
)


def _file_exists(path: str) -> bool:
    return Path(path).is_file()


class SourceUnavailableError(Exception):
    """İletilecek kaynak mesaja veya fotoğraf dosyasına erişilemiyor."""


@dataclass(slots=True, frozen=True)
class ContactCard:
    phone: str
    first_name: str
    last_name: str = ""


@dataclass(slots=True)
class OutgoingContent:
    """Gönderilecek içeriğin DB'den bağımsız anlık görüntüsü."""

    content_type: ContentType = ContentType.TEXT
    text: str = ""
    entities: list[EntityDict] = field(default_factory=list)
    photo_path: str | None = None
    source_peer: str | None = None
    source_msg_id: int | None = None
    hide_forward_source: bool = False
    contact: ContactCard | None = None
    text_fallback: bool = True

    @classmethod
    def from_auto_config(cls, cfg: AutoMessageConfig) -> OutgoingContent:
        contact = None
        if cfg.has_contact:
            contact = ContactCard(
                phone=cfg.contact_phone or "",
                first_name=cfg.contact_first_name or "",
                last_name=cfg.contact_last_name or "",
            )
        return cls(
            content_type=cfg.content_type,
            text=cfg.text or "",
            entities=list(cfg.entities or []),
            photo_path=cfg.photo_path,
            source_peer=cfg.source_peer,
            source_msg_id=cfg.source_msg_id,
            hide_forward_source=cfg.hide_forward_source,
            contact=contact,
            text_fallback=cfg.text_fallback_on_media_forbidden,
        )

    @classmethod
    def from_dm_config(cls, cfg: DMAutoReplyConfig) -> OutgoingContent:
        text, entities = cfg.text or "", list(cfg.entities or [])
        if cfg.whatsapp_url:
            # Userbot buton gönderemez; bot üzerinden gönderilemezse link metnin sonuna eklenir.
            text, entities = append_link(text, entities, cfg.button_text, cfg.whatsapp_url)
        return cls(
            content_type=ContentType.PHOTO if cfg.photo_path else ContentType.TEXT,
            text=text,
            entities=entities,
            photo_path=cfg.photo_path,
        )


@dataclass(slots=True)
class SendOutcome:
    fallback_used: bool = False
    contact_sent: bool = False
    # Ana mesaj gittikten sonra kişi kartı FloodWait aldıysa: ana mesaj tekrar gönderilmesin,
    # sadece hesap genelinde beklensin diye ayrı raporlanır.
    flood_seconds: int = 0


async def resolve_peer(client: TelegramClient, peer: str) -> Any:
    """'@kullaniciadi' veya '-100…' biçimindeki kaynağı Telethon input entity'sine çevirir."""
    if peer.startswith("@"):
        return await client.get_input_entity(peer[1:])
    chat_id = int(peer)
    try:
        return await client.get_input_entity(chat_id)
    except ValueError:
        # Varlık önbellekte yok: diyalogları bir kez tarayıp tekrar dene.
        await client.get_dialogs(limit=None)
        return await client.get_input_entity(chat_id)


async def fetch_source_message(
    client: TelegramClient, peer: str, message_id: int
) -> tuple[Any, Any]:
    try:
        entity = await resolve_peer(client, peer)
        message = await client.get_messages(entity, ids=message_id)
    except (
        ValueError,
        errors.ChannelPrivateError,
        errors.ChannelInvalidError,
        errors.UsernameNotOccupiedError,
        errors.UsernameInvalidError,
        errors.MessageIdInvalidError,
    ) as exc:
        raise SourceUnavailableError(
            "Userbot bu kanala erişemiyor. Hesabın kanala üye olduğundan emin olun."
        ) from exc
    if message is None or isinstance(message, tl.MessageEmpty):
        raise SourceUnavailableError("Kaynak mesaj bulunamadı veya silinmiş.")
    return entity, message


class MessageSender:
    """Bir içerik için gönderim mantığı; bir döngü boyunca tekrar kullanılır.

    Fotoğraf döngü başına yalnızca bir kez yüklenir, sonraki gruplarda Telegram'daki kopyası
    (``message.photo``) kullanılır.
    """

    def __init__(self, client: TelegramClient, content: OutgoingContent) -> None:
        self._client = client
        self._content = content
        self._entities = to_telethon_entities(content.entities)
        self._media: Any = None
        self._media_lock = asyncio.Lock()
        self._source_entity: Any = None
        self._source_message: Any = None
        self._fallback_text = content.text
        self._fallback_entities = self._entities

    @property
    def content(self) -> OutgoingContent:
        return self._content

    async def prepare(self) -> None:
        content = self._content
        if content.content_type == ContentType.FORWARD:
            if not content.source_peer or not content.source_msg_id:
                raise SourceUnavailableError("İletilecek mesaj ayarlanmamış.")
            self._source_entity, self._source_message = await fetch_source_message(
                self._client, content.source_peer, content.source_msg_id
            )
            self._fallback_text = self._source_message.message or ""
            self._fallback_entities = list(self._source_message.entities or [])
        elif content.content_type == ContentType.PHOTO and (
            not content.photo_path or not _file_exists(content.photo_path)
        ):
            raise SourceUnavailableError("Fotoğraf dosyası bulunamadı, mesajı yeniden ayarlayın.")

    @property
    def source_has_media(self) -> bool:
        return bool(self._source_message is not None and self._source_message.media)

    async def send(self, peer: Any, *, media_allowed: bool = True) -> SendOutcome:
        outcome = SendOutcome()
        kind = self._content.content_type
        if kind == ContentType.TEXT:
            await self._send_text(peer, self._content.text, self._entities)
        elif kind == ContentType.PHOTO:
            outcome.fallback_used = await self._with_fallback(
                peer, media_allowed, lambda: self._send_photo(peer)
            )
        else:
            needs_media = self.source_has_media
            outcome.fallback_used = await self._with_fallback(
                peer, media_allowed or not needs_media, lambda: self._forward(peer)
            )
        if self._content.contact is not None:
            await self._send_contact(peer, outcome)
        return outcome

    async def _with_fallback(self, peer: Any, media_allowed: bool, send_media) -> bool:
        """Medya gönderilemeyen gruplara (izin varsa) sadece metni gönderir."""
        can_fallback = self._content.text_fallback and bool(self._fallback_text.strip())
        if not media_allowed:
            if not can_fallback:
                raise errors.ChatSendMediaForbiddenError(request=None)
            await self._send_text(peer, self._fallback_text, self._fallback_entities)
            return True
        try:
            await send_media()
            return False
        except _MEDIA_ERRORS:
            if not can_fallback:
                raise
            await self._send_text(peer, self._fallback_text, self._fallback_entities)
            return True

    async def _send_text(self, peer: Any, text: str, entities: list[Any]) -> Any:
        # formatting_entities her zaman liste verilir; None verilirse Telethon metni
        # markdown olarak ayrıştırıp '*' ve '_' karakterlerini bozar.
        return await self._client.send_message(
            peer, text, formatting_entities=list(entities), link_preview=True
        )

    async def _send_photo(self, peer: Any) -> Any:
        async with self._media_lock:
            if self._media is None:
                self._media = await self._client.upload_file(self._content.photo_path)
        message = await self._client.send_file(
            peer,
            self._media,
            caption=self._content.text,
            formatting_entities=list(self._entities),
        )
        photo = getattr(message, "photo", None)
        if photo is not None and isinstance(self._media, tl.InputFile | tl.InputFileBig):
            self._media = photo
        return message

    async def _forward(self, peer: Any) -> Any:
        return await self._client.forward_messages(
            peer,
            self._source_message.id,
            from_peer=self._source_entity,
            drop_author=True if self._content.hide_forward_source else None,
        )

    async def _send_contact(self, peer: Any, outcome: SendOutcome) -> None:
        contact = self._content.contact
        assert contact is not None
        media = tl.InputMediaContact(
            phone_number=contact.phone,
            first_name=contact.first_name,
            last_name=contact.last_name,
            vcard="",
        )
        try:
            await self._client.send_file(peer, media)
            outcome.contact_sent = True
        except errors.RPCError as exc:
            action = classify(exc)
            if action in {ErrorAction.ACCOUNT_LIMITED, ErrorAction.SESSION_DEAD}:
                raise
            if action == ErrorAction.FLOOD:
                outcome.flood_seconds = wait_seconds(exc)
            # Ana mesaj gitti; kişi kartı hatası döngüyü bozmaz.
            log.info("Kişi kartı gönderilemedi (%s): %s", peer, exc)
