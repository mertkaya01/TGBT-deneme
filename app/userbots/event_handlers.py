"""Userbot olay dinleyicileri: DM oto-cevap ve grup yanıt filtreleri."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from telethon import errors, events

from app.database import repositories as repo
from app.userbots.broadcast import TELEGRAM_SERVICE_ID
from app.userbots.errors import ErrorAction, classify, wait_seconds
from app.utils.text import tr_lower

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.userbots.runtime import AccountRuntime

log = logging.getLogger(__name__)

# Flood beklemesi bundan uzunsa oto-cevaplar beklemeden atlanır (kuyruk birikmesin).
MAX_REPLY_WAIT_SEC = 30


class UserbotEventHandlers:
    def __init__(self, runtime: AccountRuntime, session_maker: async_sessionmaker) -> None:
        self._rt = runtime
        self._session_maker = session_maker
        self._private_filter = events.NewMessage(incoming=True, func=lambda e: e.is_private)
        self._group_filter = events.NewMessage(incoming=True, func=lambda e: e.is_group)

    def register(self) -> None:
        client = self._rt.client
        client.add_event_handler(self.on_private_message, self._private_filter)
        client.add_event_handler(self.on_group_message, self._group_filter)

    def unregister(self) -> None:
        client = self._rt.client
        client.remove_event_handler(self.on_private_message, self._private_filter)
        client.remove_event_handler(self.on_group_message, self._group_filter)

    # ------------------------------------------------------------------ DM oto-cevap

    async def on_private_message(self, event: Any) -> None:
        rt = self._rt
        if not rt.dm_auto_reply_enabled or rt.dm_sender is None:
            return
        peer_id = event.sender_id or event.chat_id
        if (
            not peer_id
            or peer_id in (rt.me_id, TELEGRAM_SERVICE_ID)
            or peer_id in rt.dm_known_peers
            or peer_id in rt.dm_inflight
        ):
            return
        # Aynı kişiden art arda gelen mesajlar için tek cevap.
        rt.dm_inflight.add(peer_id)
        try:
            await self._maybe_auto_reply(event, peer_id)
        except errors.RPCError as exc:
            if classify(exc) == ErrorAction.FLOOD:
                rt.flood_gate.penalize(wait_seconds(exc) + 1)
            log.info("[%s] DM oto-cevap gönderilemedi: %s", rt.name, exc)
        except Exception:
            log.exception("[%s] DM oto-cevap hatası", rt.name)
        finally:
            rt.dm_inflight.discard(peer_id)

    async def _maybe_auto_reply(self, event: Any, peer_id: int) -> None:
        rt = self._rt
        sender = await event.get_sender()
        if sender is None or getattr(sender, "bot", False) or getattr(sender, "support", False):
            rt.dm_known_peers.add(peer_id)
            return
        if rt.dm_skip_contacts and getattr(sender, "contact", False):
            return

        async with self._session_maker() as session:
            state = await repo.get_replied_state(session, rt.account_id, peer_id)
        if state is not None:
            rt.dm_known_peers.add(peer_id)
            return

        # "İlk kez yazan" kontrolü: bu mesajdan önce sohbette mesaj varsa kişi zaten tanıdık.
        older = await rt.client.get_messages(event.chat_id, limit=1, max_id=event.id)
        if older:
            await self._remember(peer_id, replied=False)
            return

        if rt.flood_gate.remaining > MAX_REPLY_WAIT_SEC:
            return
        await rt.flood_gate.wait()
        await rt.dm_sender.prepare()
        await rt.dm_sender.send(await event.get_input_chat())
        await self._remember(peer_id, replied=True)
        log.info("[%s] DM oto-cevap gönderildi: %s", rt.name, peer_id)

    async def _remember(self, peer_id: int, *, replied: bool) -> None:
        self._rt.dm_known_peers.add(peer_id)
        async with self._session_maker() as session:
            await repo.mark_replied(session, self._rt.account_id, peer_id, replied)
            await session.commit()

    # ------------------------------------------------------------------ grup filtreleri

    async def on_group_message(self, event: Any) -> None:
        rt = self._rt
        if not rt.filters:
            return
        chat_id = event.chat_id
        if chat_id in rt.exception_ids:
            return
        text = event.raw_text
        if not text:
            return

        normalized = tr_lower(text)
        matched = next((f for f in rt.filters if f.matches(normalized)), None)
        if matched is None:
            return

        now = time.monotonic()
        key = (chat_id, matched.id)
        if rt.filter_cooldowns.get(key, 0) > now or rt.flood_gate.remaining > 0:
            return
        sender = await event.get_sender()
        if getattr(sender, "bot", False):
            return  # başka botlarla yanıt döngüsüne girme
        rt.filter_cooldowns[key] = now + matched.cooldown_sec
        rt.prune_cooldowns()

        try:
            await rt.client.send_message(
                await event.get_input_chat(),
                matched.reply_text,
                formatting_entities=list(matched.reply_entities),
                reply_to=event.id,
            )
        except errors.RPCError as exc:
            if classify(exc) == ErrorAction.FLOOD:
                rt.flood_gate.penalize(wait_seconds(exc) + 1)
            log.info("[%s] filtre yanıtı gönderilemedi (%s): %s", rt.name, chat_id, exc)
