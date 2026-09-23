"""Bot, Dispatcher ve FSM storage kurulumu."""

from __future__ import annotations

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.base import BaseStorage
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import DefaultKeyBuilder, RedisStorage
from aiogram.types import BotCommand
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import Settings
from app.handlers import build_root_router
from app.middlewares.auth import AuthMiddleware
from app.middlewares.db import DbSessionMiddleware
from app.userbots.userbot_manager import UserbotManager

BOT_COMMANDS = [
    BotCommand(command="start", description="Hesaplarım / ana menü"),
    BotCommand(command="cancel", description="Mevcut işlemi iptal et"),
    BotCommand(command="help", description="Bu bot ne işe yarar?"),
]


def create_bot(settings: Settings) -> Bot:
    return Bot(
        token=settings.bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True),
    )


def create_storage(redis: Redis | None) -> BaseStorage:
    if redis is None:
        return MemoryStorage()
    return RedisStorage(redis, key_builder=DefaultKeyBuilder(prefix="tgbt:fsm"))


def create_dispatcher(
    settings: Settings,
    storage: BaseStorage,
    session_maker: async_sessionmaker,
    manager: UserbotManager,
) -> Dispatcher:
    dp = Dispatcher(storage=storage, settings=settings, manager=manager)
    # Sıra önemli: önce DB oturumu açılır, sonra yetki kontrolü bu oturumu kullanır.
    dp.update.outer_middleware(DbSessionMiddleware(session_maker))
    dp.update.outer_middleware(AuthMiddleware(settings))
    dp.include_router(build_root_router())
    return dp
