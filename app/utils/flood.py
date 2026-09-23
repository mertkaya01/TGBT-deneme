"""Hesap genelinde FloodWait yönetimi."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable


class FloodGate:
    """Bir hesap FloodWait aldığında, o hesabın tüm gönderimlerini aynı süre bekletir.

    3'lü grupta paralel giden istekler de dahil olmak üzere herkes ``wait()`` çağırır; böylece
    tek bir FloodWait sonrası diğer istekler de hemen sunucuya çarpıp cezayı büyütmez.
    """

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._clock = clock
        self._sleep = sleep
        self._until = 0.0

    def penalize(self, seconds: float) -> None:
        self._until = max(self._until, self._clock() + max(seconds, 0))

    @property
    def remaining(self) -> float:
        return max(0.0, self._until - self._clock())

    async def wait(self) -> None:
        # Döngü bilinçli: beklerken yeni bir FloodWait süreyi uzatabilir.
        while (remaining := self.remaining) > 0:
            await self._sleep(remaining)
