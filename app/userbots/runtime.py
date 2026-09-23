"""Bağlı bir userbot'un bellek içi durumu."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.database.models import MatchType
from app.utils.flood import FloodGate
from app.utils.text import keyword_matches

if TYPE_CHECKING:
    from telethon import TelegramClient

    from app.userbots.broadcast import BroadcastJob
    from app.userbots.sender import MessageSender


@dataclass(slots=True, frozen=True)
class CompiledFilter:
    id: int
    keywords: tuple[str, ...]
    match_type: MatchType
    reply_text: str
    reply_entities: tuple[Any, ...]
    cooldown_sec: int

    def matches(self, normalized_text: str) -> bool:
        return any(keyword_matches(normalized_text, kw, self.match_type) for kw in self.keywords)


@dataclass(slots=True, frozen=True)
class GroupInfo:
    chat_id: int
    title: str
    archived: bool


@dataclass(eq=False)
class AccountRuntime:
    """Hesap başına tek nesne: Telethon istemcisi + event handler'ların okuduğu ayar önbelleği.

    Event handler'lar (yoğun gruplarda saniyede onlarca mesaj) her mesajda DB'ye gitmesin diye
    filtreler, istisnalar ve DM ayarı burada tutulur; panelden değişiklik olunca
    ``UserbotManager.refresh_settings`` ile yenilenir.
    """

    account_id: int
    owner_id: int
    name: str
    client: TelegramClient
    me_id: int
    flood_gate: FloodGate = field(default_factory=FloodGate)

    # --- ayar önbelleği
    dm_auto_reply_enabled: bool = False
    dm_skip_contacts: bool = False
    dm_sender: MessageSender | None = None
    filters: list[CompiledFilter] = field(default_factory=list)
    exception_ids: set[int] = field(default_factory=set)

    # --- çalışma durumu
    filter_cooldowns: dict[tuple[int, int], float] = field(default_factory=dict)
    slowmode_until: dict[int, float] = field(default_factory=dict)
    dm_known_peers: set[int] = field(default_factory=set)
    dm_inflight: set[int] = field(default_factory=set)
    worker_task: asyncio.Task | None = None
    broadcast: BroadcastJob | None = None
    groups_cache: tuple[float, list[GroupInfo]] | None = None
    long_flood_notified_until: float = 0.0

    @property
    def worker_running(self) -> bool:
        return self.worker_task is not None and not self.worker_task.done()

    @property
    def broadcast_running(self) -> bool:
        return self.broadcast is not None and self.broadcast.running

    def is_slowmode_blocked(self, chat_id: int) -> bool:
        until = self.slowmode_until.get(chat_id)
        if until is None:
            return False
        if until <= time.monotonic():
            del self.slowmode_until[chat_id]
            return False
        return True

    def prune_cooldowns(self) -> None:
        now = time.monotonic()
        if len(self.filter_cooldowns) > 5000:
            self.filter_cooldowns = {k: v for k, v in self.filter_cooldowns.items() if v > now}
