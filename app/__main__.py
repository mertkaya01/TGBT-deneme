"""Giriş noktası: python -m app"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sys

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramUnauthorizedError
from pydantic import ValidationError
from redis.asyncio import Redis

from app.bot_factory import BOT_COMMANDS, create_bot, create_dispatcher, create_storage
from app.config import Settings, get_settings
from app.database.base import Base, create_engine, create_session_maker
from app.database.migrate import run_migrations
from app.userbots.userbot_manager import UserbotManager
from app.utils.crypto import SessionCipher
from app.utils.logging import setup_logging
from app.utils.redis_lock import LockFactory

log = logging.getLogger("app")


def make_notifier(bot: Bot):
    async def notify(user_id: int, text: str) -> None:
        try:
            await bot.send_message(user_id, text)
        except TelegramForbiddenError:
            log.info("Kullanıcı %s botu engellemiş, bildirim atlanıyor", user_id)

    return notify


async def connect_redis(settings: Settings) -> Redis | None:
    if not settings.redis_url:
        log.warning("REDIS_URL tanımlı değil: FSM bellekte tutulacak (yalnızca geliştirme için).")
        return None
    redis = Redis.from_url(settings.redis_url)
    await redis.ping()
    return redis


async def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    settings.media_dir.mkdir(parents=True, exist_ok=True)

    engine = create_engine(settings.database_url)
    if settings.auto_migrate:
        await run_migrations(settings.database_url)
    else:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    session_maker = create_session_maker(engine)

    redis = await connect_redis(settings)
    bot = create_bot(settings)
    manager = UserbotManager(
        settings,
        session_maker,
        SessionCipher(settings.session_encryption_key.get_secret_value()),
        make_notifier(bot),
        LockFactory(redis),
    )
    dp = create_dispatcher(settings, create_storage(redis), session_maker, manager)

    async def on_startup() -> None:
        await bot.set_my_commands(BOT_COMMANDS)
        await manager.start()
        me = await bot.get_me()
        log.info("Controller bot hazır: @%s", me.username)

    async def on_shutdown() -> None:
        log.info("Kapatılıyor: userbot'lar durduruluyor…")
        await manager.shutdown()

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    try:
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()
        if redis is not None:
            await redis.aclose()
        await engine.dispose()


def run() -> None:
    try:
        get_settings()
    except ValidationError as exc:
        missing = ", ".join(str(err["loc"][0]).upper() for err in exc.errors())
        print(f"Yapılandırma hatası: şu değişkenler eksik/geçersiz: {missing}", file=sys.stderr)
        print(".env.example dosyasını .env olarak kopyalayıp doldurun.", file=sys.stderr)
        raise SystemExit(1) from None
    try:
        with contextlib.suppress(KeyboardInterrupt):
            asyncio.run(main())
    except TelegramUnauthorizedError:
        print("BOT_TOKEN geçersiz: @BotFather'dan aldığınız token'ı kontrol edin.", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    run()
