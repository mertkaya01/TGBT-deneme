"""Uçtan uca bot testleri için sahte Telegram API ve güncelleme yardımcıları."""

from __future__ import annotations

import itertools
from datetime import datetime
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.methods import EditMessageText, SendMessage, TelegramMethod
from aiogram.types import CallbackQuery, Chat, Message, MessageEntity, Update
from aiogram.types import User as TgUser

ADMIN_ID = 1
STRANGER_ID = 99
_ids = itertools.count(1)


class RecordingSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.requests: list[TelegramMethod[Any]] = []

    async def make_request(self, bot: Bot, method: TelegramMethod[Any], timeout: int | None = None):  # noqa: ASYNC109
        self.requests.append(method)
        if isinstance(method, SendMessage):
            return Message(
                message_id=next(_ids),
                date=datetime.now(),
                chat=Chat(id=int(method.chat_id), type="private"),
                text=method.text,
            ).as_(bot)
        return True

    async def stream_content(self, *args, **kwargs):  # pragma: no cover - kullanılmıyor
        yield b""

    async def close(self) -> None:
        pass

    def take(self) -> list[TelegramMethod[Any]]:
        requests, self.requests = self.requests, []
        return requests


def texts_of(requests: list[TelegramMethod[Any]]) -> list[str]:
    return [r.text for r in requests if isinstance(r, SendMessage | EditMessageText)]


def buttons_of(request: SendMessage | EditMessageText) -> list[str]:
    markup = request.reply_markup
    return [b.text for row in markup.inline_keyboard for b in row] if markup else []


def tg_user(user_id: int) -> TgUser:
    return TgUser(id=user_id, is_bot=False, first_name=f"Kullanıcı{user_id}")


async def send_text(dp: Dispatcher, bot: Bot, text: str, user_id: int = ADMIN_ID) -> None:
    entities = None
    if text.startswith("/"):
        entities = [MessageEntity(type="bot_command", offset=0, length=len(text.split()[0]))]
    message = Message(
        message_id=next(_ids),
        date=datetime.now(),
        chat=Chat(id=user_id, type="private"),
        from_user=tg_user(user_id),
        text=text,
        entities=entities,
    )
    await dp.feed_update(bot, Update(update_id=next(_ids), message=message.as_(bot)))


async def press(dp: Dispatcher, bot: Bot, data: str, user_id: int = ADMIN_ID) -> None:
    message = Message(
        message_id=next(_ids),
        date=datetime.now(),
        chat=Chat(id=user_id, type="private"),
        from_user=TgUser(id=42, is_bot=True, first_name="Bot"),
        text="panel",
    )
    callback = CallbackQuery(
        id=str(next(_ids)),
        from_user=tg_user(user_id),
        chat_instance="x",
        message=message,
        data=data,
    )
    await dp.feed_update(bot, Update(update_id=next(_ids), callback_query=callback.as_(bot)))
