"""Userbot olay dinleyicileri: DM oto-cevap ve grup yanıt filtreleri."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from telethon import errors, events

from app.database import repositories as repo
from app.database.models import DMReplyMode, utcnow
from app.userbots.broadcast import TELEGRAM_SERVICE_ID
from app.userbots.errors import ErrorAction, classify, wait_seconds
from app.userbots.runtime import DM_REPLY_INLINE_QUERY, ControllerBot
from app.utils.text import tr_lower

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.userbots.runtime import AccountRuntime

log = logging.getLogger(__name__)

# Flood beklemesi bundan uzunsa oto-cevaplar beklemeden atlanır (kuyruk birikmesin).
MAX_REPLY_WAIT_SEC = 30


class UserbotEventHandlers:
    def __init__(
        self,
        runtime: AccountRuntime,
        session_maker: async_sessionmaker,
        controller_bot: ControllerBot | None = None,
    ) -> None:
        self._rt = runtime
        self._session_maker = session_maker
        self._bot = controller_bot or ControllerBot()
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
        if not peer_id or peer_id in (rt.me_id, TELEGRAM_SERVICE_ID) or peer_id in rt.dm_inflight:
            return
        if rt.dm_mode == DMReplyMode.FIRST and peer_id in rt.dm_known_peers:
            return
        if rt.dm_mode == DMReplyMode.ALWAYS and self._in_cooldown(peer_id):
            return
        # Aynı kişiden art arda gelen mesajlar için tek cevap.
        rt.dm_inflight.add(peer_id)
        try:
            if rt.dm_mode == DMReplyMode.ALWAYS:
                await self._reply_every_message(event, peer_id)
            else:
                await self._reply_first_message(event, peer_id)
        except errors.RPCError as exc:
            if classify(exc) == ErrorAction.FLOOD:
                rt.flood_gate.penalize(wait_seconds(exc) + 1)
            log.info("[%s] DM oto-cevap gönderilemedi: %s", rt.name, exc)
        except Exception:
            log.exception("[%s] DM oto-cevap hatası", rt.name)
        finally:
            rt.dm_inflight.discard(peer_id)

    async def _accepts_sender(self, event: Any, peer_id: int) -> bool:
        """Botlara, Telegram destek hesaplarına ve (ayara göre) rehberdekilere cevap verilmez."""
        sender = await event.get_sender()
        if sender is None or getattr(sender, "bot", False) or getattr(sender, "support", False):
            self._rt.dm_known_peers.add(peer_id)
            return False
        return not (self._rt.dm_skip_contacts and getattr(sender, "contact", False))

    async def _reply_first_message(self, event: Any, peer_id: int) -> None:
        """Mod: sadece ilk mesaja. Kişiye daha önce yazılmışsa (ya da o yazmışsa) cevap yok."""
        rt = self._rt
        if not await self._accepts_sender(event, peer_id):
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
        if await self._send_reply(event):
            await self._remember(peer_id, replied=True)

    async def _reply_every_message(self, event: Any, peer_id: int) -> None:
        """Mod: her mesaja. Aynı kişiye bekleme süresi dolmadan tekrar cevap verilmez."""
        rt = self._rt
        if not await self._accepts_sender(event, peer_id):
            return
        # Hesap bu kişiye yakın zamanda (elle/otomatik) yazdıysa sohbet sürüyordur: araya girme.
        last_out = await rt.client.get_messages(event.chat_id, limit=1, from_user="me")
        if last_out and getattr(last_out[0], "date", None):
            elapsed = (utcnow() - last_out[0].date).total_seconds()
            if elapsed < rt.dm_cooldown_sec:
                rt.dm_last_reply[peer_id] = time.monotonic() - max(elapsed, 0)
                return
        if await self._send_reply(event):
            rt.dm_last_reply[peer_id] = time.monotonic()
            await self._remember(peer_id, replied=True)

    def _in_cooldown(self, peer_id: int) -> bool:
        last = self._rt.dm_last_reply.get(peer_id)
        return last is not None and time.monotonic() - last < self._rt.dm_cooldown_sec

    async def _send_reply(self, event: Any) -> bool:
        """Cevabı gönderir. WhatsApp butonu varsa bot üzerinden (inline), yoksa doğrudan."""
        rt = self._rt
        if rt.flood_gate.remaining > MAX_REPLY_WAIT_SEC:
            return False
        await rt.flood_gate.wait()
        peer = await event.get_input_chat()
        if rt.dm_has_button and self._bot.can_use_inline() and await self._send_via_bot(peer):
            log.info("[%s] DM oto-cevap (butonlu) gönderildi: %s", rt.name, event.chat_id)
            return True
        assert rt.dm_sender is not None
        await rt.dm_sender.prepare()
        await rt.dm_sender.send(peer)
        log.info("[%s] DM oto-cevap gönderildi: %s", rt.name, event.chat_id)
        return True

    async def _send_via_bot(self, peer: Any) -> bool:
        """Userbot buton gönderemez; controller bot'un inline sonucunu sohbete bırakır."""
        rt = self._rt
        try:
            results = await rt.client.inline_query(
                self._bot.username, DM_REPLY_INLINE_QUERY, entity=peer
            )
            if not results:
                return False
            await results[0].click(peer)
        except errors.BotInlineDisabledError:
            log.warning(
                "[%s] @%s için inline mod kapalı (BotFather → /setinline); link ile gönderiliyor",
                rt.name,
                self._bot.username,
            )
            self._bot.mark_inline_failed()
            return False
        except errors.RPCError as exc:
            if classify(exc) in {
                ErrorAction.FLOOD,
                ErrorAction.ACCOUNT_LIMITED,
                ErrorAction.SESSION_DEAD,
            }:
                raise
            log.info("[%s] butonlu cevap gönderilemedi, link ile denenecek: %s", rt.name, exc)
            return False
        self._bot.mark_inline_ok()
        return True

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
