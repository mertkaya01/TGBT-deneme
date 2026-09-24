"""Beyaz liste erişim kontrolü.

Kullanıcı kaydı her güncellemede güncellenir; yalnızca admin veya izin verilmiş kullanıcılar
handler'lara ulaşır. İlk kez gelen yetkisiz kullanıcılar için adminlere onay bildirimi gider.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware, Bot
from aiogram.types import TelegramObject, Update
from aiogram.types import User as TgUser
from sqlalchemy.ext.asyncio import AsyncSession

from app import texts
from app.config import Settings
from app.database import repositories as repo
from app.keyboards.inline import admin_new_user

log = logging.getLogger(__name__)


class AuthMiddleware(BaseMiddleware):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user: TgUser | None = data.get("event_from_user")
        if tg_user is None or tg_user.is_bot:
            return None
        if isinstance(event, Update) and event.inline_query is not None:
            # Butonlu oto-cevap için userbot hesaplarından gelen inline sorgular: handler, sorguyu
            # yalnızca kayıtlı bir userbot hesabından geliyorsa cevaplar.
            return await handler(event, data)
        session: AsyncSession = data["session"]
        user, created = await repo.upsert_user(
            session,
            tg_user.id,
            tg_user.username,
            tg_user.full_name,
            self._settings.admin_ids,
        )
        if session.dirty or session.new:
            await session.commit()

        if user.has_access:
            data["db_user"] = user
            return await handler(event, data)

        if user.is_banned:
            return None
        if isinstance(event, Update):
            bot: Bot = data["bot"]
            await self._deny(bot, event, tg_user)
            if created:
                await self._notify_admins(bot, tg_user)
        return None

    @staticmethod
    async def _deny(bot: Bot, update: Update, tg_user: TgUser) -> None:
        text = texts.ACCESS_DENIED.format(user_id=tg_user.id)
        try:
            if update.callback_query:
                await update.callback_query.answer(
                    texts.ACCESS_DENIED.split("\n")[0], show_alert=True
                )
            elif update.message and update.message.chat.type == "private":
                await bot.send_message(tg_user.id, text)
        except Exception:
            log.debug("Erişim reddi mesajı gönderilemedi", exc_info=True)

    async def _notify_admins(self, bot: Bot, tg_user: TgUser) -> None:
        text = texts.NOTIFY_NEW_USER.format(
            name=texts.html(tg_user.full_name),
            username=f"@{tg_user.username}" if tg_user.username else "—",
            user_id=tg_user.id,
        )
        for admin_id in self._settings.admin_ids:
            try:
                await bot.send_message(admin_id, text, reply_markup=admin_new_user(tg_user.id))
            except Exception:
                log.debug("Admin %s bilgilendirilemedi", admin_id, exc_info=True)
