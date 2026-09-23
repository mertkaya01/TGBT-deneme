"""Zamanlanmış otomatik mesaj döngüsü.

Akış (hesap başına tek ``asyncio.Task``):

1. Ayarları DB'den taze oku (panelden yapılan değişiklikler bir sonraki turda geçerli olur).
2. Son döngüden bu yana ``cycle_minutes`` geçmediyse kalan süreyi bekle
   (bot yeniden başlasa bile gruplara erken tekrar mesaj gitmez).
3. Hedef grupları topla → ``batch_size``'lık (varsayılan 3) paketlere böl.
4. Her paketi paralel gönder, paketler arasında ``min_delay``–``max_delay`` sn rastgele bekle.
5. Tur bitince istatistikleri yaz, ``cycle_minutes`` dakika bekle, başa dön.

Tüm beklemeler ``asyncio.sleep`` olduğu için event loop hiç bloklanmaz ve durdurma
(``task.cancel()``) beklemenin ortasında bile anında gerçekleşir.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import update
from telethon import errors
from telethon.tl import types as tl

from app import texts
from app.database import repositories as repo
from app.database.models import Account, AccountStatus, AutoMessageConfig, ContentType, utcnow
from app.userbots.errors import (
    AccountLimitedError,
    ErrorAction,
    SessionDeadError,
    classify,
    wait_seconds,
)
from app.userbots.sender import MessageSender, OutgoingContent, SourceUnavailableError
from app.utils.text import chunked, format_duration

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.config import Settings
    from app.userbots.runtime import AccountRuntime
    from app.utils.redis_lock import DistributedLock

log = logging.getLogger(__name__)

Notifier = Callable[[int, str], Awaitable[None]]
MAX_SEND_ATTEMPTS = 3
ERROR_NOTIFY_THRESHOLD = 3


class WorkerExit(StrEnum):
    STOPPED = "stopped"
    NOT_CONFIGURED = "not_configured"
    SOURCE_UNAVAILABLE = "source_unavailable"
    ACCOUNT_LIMITED = "account_limited"
    SESSION_DEAD = "session_dead"


@dataclass(slots=True, frozen=True)
class CycleSettings:
    content: OutgoingContent
    configured: bool
    batch_size: int
    min_delay_sec: float
    max_delay_sec: float
    cycle_minutes: int
    include_archived: bool
    last_started: datetime | None
    last_finished: datetime | None
    exception_ids: frozenset[int]

    @classmethod
    def from_config(cls, cfg: AutoMessageConfig, exception_ids: set[int]) -> CycleSettings:
        return cls(
            content=OutgoingContent.from_auto_config(cfg),
            configured=cfg.is_configured,
            batch_size=max(1, cfg.batch_size),
            min_delay_sec=max(0.0, cfg.min_delay_sec),
            max_delay_sec=max(cfg.min_delay_sec, cfg.max_delay_sec),
            cycle_minutes=max(1, cfg.cycle_minutes),
            include_archived=cfg.include_archived,
            last_started=cfg.last_cycle_started_at,
            last_finished=cfg.last_cycle_finished_at,
            exception_ids=frozenset(exception_ids),
        )

    def next_run_at(self) -> datetime | None:
        """Son turun başlangıç/bitişinden hangisi daha yeniyse onun üzerine döngü süresi.

        Yarıda kesilen bir tur (başlangıç > bitiş) de sayılır; böylece restart sonrası
        o turda mesaj almış gruplara hemen tekrar gönderilmez.
        """
        marks = [m for m in (self.last_started, self.last_finished) if m is not None]
        if not marks:
            return None
        return max(marks) + timedelta(minutes=self.cycle_minutes)


@dataclass(slots=True, frozen=True)
class Target:
    chat_id: int
    title: str
    peer: Any
    media_allowed: bool


@dataclass(slots=True)
class CycleStats:
    targets: int = 0
    sent: int = 0
    failed: int = 0
    skipped: int = 0
    fallback: int = 0


def _rights_forbid(entity: Any, right: str) -> bool:
    """Grup izinleri bu eylemi yasaklıyor mu? (Kurucu/adminler için yasak yok sayılır.)"""
    if getattr(entity, "creator", False) or getattr(entity, "admin_rights", None):
        return False
    for rights in (
        getattr(entity, "banned_rights", None),
        getattr(entity, "default_banned_rights", None),
    ):
        if rights is not None and getattr(rights, right, False):
            return True
    return False


def build_target(dialog: Any, content: OutgoingContent) -> Target | None:
    """Diyalog gönderime uygunsa ``Target`` döndürür, değilse ``None``."""
    entity = dialog.entity
    if isinstance(entity, tl.ChatForbidden | tl.ChannelForbidden):
        return None
    if getattr(entity, "left", False) or getattr(entity, "deactivated", False):
        return None
    if getattr(entity, "migrated_to", None) is not None:
        return None  # süpergruba dönüşmüş eski grup; süpergrup ayrıca listelenir
    if _rights_forbid(entity, "send_messages"):
        return None
    if content.content_type == ContentType.TEXT and _rights_forbid(entity, "send_plain"):
        return None
    media_allowed = not (
        _rights_forbid(entity, "send_media") or _rights_forbid(entity, "send_photos")
    )
    return Target(
        chat_id=dialog.id,
        title=dialog.name or str(dialog.id),
        peer=dialog.input_entity,
        media_allowed=media_allowed,
    )


class AutoMessageWorker:
    def __init__(
        self,
        runtime: AccountRuntime,
        session_maker: async_sessionmaker,
        settings: Settings,
        notifier: Notifier,
        lock: DistributedLock,
        *,
        skip_initial_wait: bool = False,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        rng: random.Random | None = None,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._rt = runtime
        self._session_maker = session_maker
        self._settings = settings
        self._notify = notifier
        self._lock = lock
        self._skip_initial_wait = skip_initial_wait
        self._sleep = sleep
        self._rng = rng or random.Random()
        self._clock = clock

    # ------------------------------------------------------------------ yaşam döngüsü

    async def run(self) -> WorkerExit:
        await self._acquire_lock()
        heartbeat = asyncio.create_task(self._heartbeat(asyncio.current_task()))
        try:
            return await self._loop()
        finally:
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await heartbeat
            with contextlib.suppress(Exception):
                await self._lock.release()

    async def _acquire_lock(self) -> None:
        while not await self._lock.acquire():
            log.info("[%s] döngü başka bir süreçte çalışıyor, kilit bekleniyor", self._rt.name)
            await asyncio.sleep(self._lock.ttl_ms / 2000)

    async def _heartbeat(self, main_task: asyncio.Task | None) -> None:
        interval = max(self._lock.ttl_ms / 3000, 1)
        while True:
            await asyncio.sleep(interval)
            try:
                alive = await self._lock.extend()
            except Exception:
                log.warning("[%s] kilit yenilenemedi", self._rt.name, exc_info=True)
                continue
            if not alive:
                log.error("[%s] döngü kilidi kaybedildi, worker durduruluyor", self._rt.name)
                if main_task is not None:
                    main_task.cancel()
                return

    async def _loop(self) -> WorkerExit:
        consecutive_errors = 0
        first_turn = True
        while True:
            try:
                cfg = await self._load_settings()
            except Exception:
                log.exception("[%s] ayarlar okunamadı", self._rt.name)
                await self._sleep(60)
                continue
            if cfg is None:
                return WorkerExit.STOPPED
            if not cfg.configured:
                await self._disable()
                await self._notify_owner(texts.NOTIFY_NOT_CONFIGURED)
                return WorkerExit.NOT_CONFIGURED

            if not (first_turn and self._skip_initial_wait):
                next_at = cfg.next_run_at()
                delay = (next_at - self._clock()).total_seconds() if next_at else 0
                if delay > 0:
                    await self._update_config(next_cycle_at=next_at)
                    await self._sleep(delay)
                    continue  # bekleme sonrası ayarları tekrar oku
            first_turn = False

            try:
                stats = await self.run_cycle(cfg)
            except SourceUnavailableError as exc:
                await self._disable(last_error=str(exc))
                await self._notify_owner(texts.NOTIFY_SOURCE_UNAVAILABLE, reason=str(exc))
                return WorkerExit.SOURCE_UNAVAILABLE
            except AccountLimitedError:
                await self._disable(status=AccountStatus.SPAM_LIMITED, last_error="PeerFlood")
                await self._notify_owner(texts.NOTIFY_SPAM_LIMITED)
                return WorkerExit.ACCOUNT_LIMITED
            except SessionDeadError:
                return WorkerExit.SESSION_DEAD
            except Exception as exc:
                consecutive_errors += 1
                log.exception("[%s] döngü hatası (#%d)", self._rt.name, consecutive_errors)
                if consecutive_errors == ERROR_NOTIFY_THRESHOLD:
                    await self._notify_owner(
                        texts.NOTIFY_CYCLE_ERRORS,
                        count=consecutive_errors,
                        error=texts.html(type(exc).__name__),
                    )
                await self._sleep(min(60 * 2 ** (consecutive_errors - 1), 1800))
                continue

            consecutive_errors = 0
            log.info(
                "[%s] döngü bitti: %d hedef, %d gönderildi, %d başarısız, %d atlandı",
                self._rt.name,
                stats.targets,
                stats.sent,
                stats.failed,
                stats.skipped,
            )

    # ------------------------------------------------------------------ tek tur

    async def run_cycle(self, cfg: CycleSettings) -> CycleStats:
        stats = CycleStats()
        sender = MessageSender(self._rt.client, cfg.content)
        await sender.prepare()
        targets = await self.collect_targets(cfg)
        stats.targets = len(targets)
        # Başlangıç, hazırlık başarılı olduktan sonra işaretlenir: hazırlıkta çıkan geçici bir
        # hata tam döngü süresi yerine kısa bir beklemeyle tekrar denenir.
        await self._update_config(last_cycle_started_at=self._clock(), next_cycle_at=None)

        for index, batch in enumerate(chunked(targets, cfg.batch_size)):
            if index:
                await self._sleep(self._rng.uniform(cfg.min_delay_sec, cfg.max_delay_sec))
            results = await asyncio.gather(
                *(self._deliver(sender, target, stats) for target in batch),
                return_exceptions=True,
            )
            for result in results:
                if isinstance(result, AccountLimitedError | SessionDeadError):
                    raise result
                if isinstance(result, BaseException):
                    stats.failed += 1
                    log.error("[%s] beklenmeyen gönderim hatası", self._rt.name, exc_info=result)

        finished = self._clock()
        await self._update_config(
            last_cycle_finished_at=finished,
            next_cycle_at=finished + timedelta(minutes=cfg.cycle_minutes),
            last_cycle_targets=stats.targets,
            last_cycle_sent=stats.sent,
            last_cycle_failed=stats.failed,
            last_cycle_skipped=stats.skipped,
            total_sent=AutoMessageConfig.total_sent + stats.sent,
        )
        return stats

    async def collect_targets(self, cfg: CycleSettings) -> list[Target]:
        archived = None if cfg.include_archived else False
        targets: list[Target] = []
        async for dialog in self._rt.client.iter_dialogs(archived=archived):
            if not dialog.is_group:
                continue
            if dialog.id in cfg.exception_ids or self._rt.is_slowmode_blocked(dialog.id):
                continue
            target = build_target(dialog, cfg.content)
            if target is not None:
                targets.append(target)
        return targets

    async def _deliver(self, sender: MessageSender, target: Target, stats: CycleStats) -> None:
        gate = self._rt.flood_gate
        for _ in range(MAX_SEND_ATTEMPTS):
            await gate.wait()
            try:
                outcome = await sender.send(target.peer, media_allowed=target.media_allowed)
            except errors.RPCError as exc:
                action = classify(exc)
                if action == ErrorAction.FLOOD:
                    await self._on_flood(wait_seconds(exc))
                    continue
                if action == ErrorAction.SLOW_MODE:
                    self._rt.slowmode_until[target.chat_id] = time.monotonic() + wait_seconds(exc)
                    stats.skipped += 1
                    return
                if action == ErrorAction.MEDIA_FORBIDDEN:
                    stats.skipped += 1
                    return
                if action == ErrorAction.ACCOUNT_LIMITED:
                    raise AccountLimitedError from exc
                if action == ErrorAction.SESSION_DEAD:
                    raise SessionDeadError from exc
                log.info("[%s] %s gönderilemedi: %s", self._rt.name, target.title, exc)
                stats.failed += 1
                return
            except (ConnectionError, OSError, TimeoutError, ValueError) as exc:
                log.warning("[%s] %s gönderilemedi: %r", self._rt.name, target.title, exc)
                stats.failed += 1
                return
            stats.sent += 1
            stats.fallback += int(outcome.fallback_used)
            if outcome.flood_seconds:
                await self._on_flood(outcome.flood_seconds)
            return
        stats.failed += 1

    async def _on_flood(self, seconds: int) -> None:
        self._rt.flood_gate.penalize(seconds + 1)
        log.warning("[%s] FloodWait %d sn", self._rt.name, seconds)
        now = time.monotonic()
        if (
            seconds >= self._settings.long_flood_notify_sec
            and now > self._rt.long_flood_notified_until
        ):
            self._rt.long_flood_notified_until = now + seconds
            await self._notify_owner(texts.NOTIFY_LONG_FLOOD, duration=format_duration(seconds))

    # ------------------------------------------------------------------ DB yardımcıları

    async def _load_settings(self) -> CycleSettings | None:
        async with self._session_maker() as session:
            account = await session.get(Account, self._rt.account_id)
            if account is None or not account.auto_message_enabled:
                return None
            exception_ids = await repo.exception_chat_ids(session, account.id)
            return CycleSettings.from_config(account.auto_config, exception_ids)

    async def _update_config(self, **values: Any) -> None:
        async with self._session_maker() as session:
            await session.execute(
                update(AutoMessageConfig)
                .where(AutoMessageConfig.account_id == self._rt.account_id)
                .values(**values)
            )
            await session.commit()

    async def _disable(
        self, *, status: AccountStatus | None = None, last_error: str | None = None
    ) -> None:
        values: dict[str, Any] = {"auto_message_enabled": False}
        if status is not None:
            values["status"] = status
        if last_error is not None:
            values["last_error"] = last_error
        async with self._session_maker() as session:
            await session.execute(
                update(Account).where(Account.id == self._rt.account_id).values(**values)
            )
            await session.commit()

    async def _notify_owner(self, template: str, **kwargs: Any) -> None:
        try:
            await self._notify(
                self._rt.owner_id, template.format(name=texts.html(self._rt.name), **kwargs)
            )
        except Exception:
            log.warning("[%s] bildirim gönderilemedi", self._rt.name, exc_info=True)
