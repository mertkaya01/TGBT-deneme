"""DM'deki herkese toplu mesaj gönderimi."""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from telethon import errors

from app.userbots.errors import ErrorAction, classify, wait_seconds
from app.userbots.sender import MessageSender, OutgoingContent

if TYPE_CHECKING:
    from telethon import TelegramClient

    from app.userbots.runtime import AccountRuntime

log = logging.getLogger(__name__)

TELEGRAM_SERVICE_ID = 777000


@dataclass(slots=True, frozen=True)
class DMTarget:
    user_id: int
    peer: Any


@dataclass(slots=True)
class BroadcastProgress:
    total: int
    sent: int = 0
    failed: int = 0
    finished: bool = False
    cancelled: bool = False
    abort_reason: str | None = None

    @property
    def done(self) -> int:
        return self.sent + self.failed


ProgressCallback = Callable[[BroadcastProgress], Awaitable[None]]


async def collect_dm_targets(client: TelegramClient) -> list[DMTarget]:
    """Arşiv dahil tüm özel sohbetler; botlar, silinmiş hesaplar ve servis hesapları hariç."""
    targets: list[DMTarget] = []
    async for dialog in client.iter_dialogs():
        if not dialog.is_user:
            continue
        user = dialog.entity
        if (
            getattr(user, "bot", False)
            or getattr(user, "deleted", False)
            or getattr(user, "is_self", False)
            or getattr(user, "support", False)
            or user.id == TELEGRAM_SERVICE_ID
        ):
            continue
        targets.append(DMTarget(user_id=user.id, peer=dialog.input_entity))
    return targets


class BroadcastJob:
    def __init__(
        self,
        runtime: AccountRuntime,
        content: OutgoingContent,
        targets: list[DMTarget],
        on_progress: ProgressCallback,
        *,
        min_delay: float,
        max_delay: float,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        rng: random.Random | None = None,
    ) -> None:
        self._rt = runtime
        self._content = content
        self._targets = targets
        self._on_progress = on_progress
        self._min_delay = min_delay
        self._max_delay = max(min_delay, max_delay)
        self._sleep = sleep
        self._rng = rng or random.Random()
        self.progress = BroadcastProgress(total=len(targets))
        self._task: asyncio.Task | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> asyncio.Task:
        self._task = asyncio.create_task(self._run(), name=f"broadcast:{self._rt.account_id}")
        return self._task

    def cancel(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()

    async def _run(self) -> BroadcastProgress:
        try:
            await self._send_all()
        except asyncio.CancelledError:
            self.progress.cancelled = True
        except Exception as exc:  # beklenmeyen hata: kullanıcıya bildir, görevi düşürme
            log.exception("[%s] DM toplu gönderim hatası", self._rt.name)
            self.progress.abort_reason = f"Beklenmeyen hata: {type(exc).__name__}"
        self.progress.finished = True
        await self._report()
        return self.progress

    async def _send_all(self) -> None:
        sender = MessageSender(self._rt.client, self._content)
        await sender.prepare()
        for index, target in enumerate(self._targets):
            if index:
                await self._sleep(self._rng.uniform(self._min_delay, self._max_delay))
            if not await self._send_one(sender, target):
                return
            await self._report()

    async def _send_one(self, sender: MessageSender, target: DMTarget) -> bool:
        """Kişiye gönderir. Toplu gönderim durmalıysa False döner."""
        gate = self._rt.flood_gate
        for _ in range(3):
            await gate.wait()
            try:
                await sender.send(target.peer)
            except errors.RPCError as exc:
                action = classify(exc)
                if action in {ErrorAction.FLOOD, ErrorAction.SLOW_MODE}:
                    gate.penalize(wait_seconds(exc) + 1)
                    continue
                if action == ErrorAction.ACCOUNT_LIMITED:
                    self.progress.abort_reason = (
                        "Telegram hesabı spam kısıtına aldı (PeerFlood). Bir süre bekleyin."
                    )
                    return False
                if action == ErrorAction.SESSION_DEAD:
                    self.progress.abort_reason = "Hesabın oturumu sonlandırılmış."
                    return False
                self.progress.failed += 1
                return True
            except (ConnectionError, OSError, TimeoutError, ValueError):
                self.progress.failed += 1
                return True
            self.progress.sent += 1
            return True
        self.progress.failed += 1
        return True

    async def _report(self) -> None:
        try:
            await self._on_progress(self.progress)
        except Exception:
            log.debug("İlerleme bildirimi başarısız", exc_info=True)
