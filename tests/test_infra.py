"""Altyapı testleri: migration'lar, dağıtık kilit, callback veri boyutları, model kısıtları."""

from __future__ import annotations

import os

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.database import repositories as repo
from app.database.base import Base, create_engine
from app.database.migrate import run_migrations
from app.database.models import Account, ReplyFilter, User
from app.keyboards.callbacks import AccountCB, ExceptionCB, FilterCB, NumpadCB
from app.utils.redis_lock import LocalLock, LockFactory, RedisLock

# --------------------------------------------------------------------------- migration


async def test_migrations_match_models(tmp_path):
    url = os.getenv("TEST_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/migrated.db")
    engine = create_engine(url)
    async with engine.begin() as conn:  # temiz başlangıç (PostgreSQL'de önceki testlerden kalanlar)
        await conn.run_sync(Base.metadata.drop_all)
        await conn.execute(text("DROP TABLE IF EXISTS alembic_version"))

    await run_migrations(url)
    await run_migrations(url)  # ikinci çalıştırma hiçbir şey yapmamalı

    async with engine.connect() as conn:
        diff = await conn.run_sync(
            lambda sync_conn: compare_metadata(MigrationContext.configure(sync_conn), Base.metadata)
        )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    await engine.dispose()
    assert diff == [], f"Modeller ile migration'lar uyuşmuyor: {diff}"


# --------------------------------------------------------------------------- modeller


async def test_account_delete_cascades(session_maker, account):
    async with session_maker() as session:
        await repo.add_exception_chat(session, account.id, -1, "x")
        await repo.add_filter(session, account.id, ["a"], "b", [])
        await repo.mark_replied(session, account.id, 5, True)
        await session.commit()

    async with session_maker() as session:
        await session.delete(await session.get(Account, account.id))
        await session.commit()
        assert await repo.exception_chat_ids(session, account.id) == set()
        assert await repo.count_filters(session, account.id) == 0
        assert await session.get(ReplyFilter, 1) is None


async def test_account_name_unique_per_owner(session_maker, account, cipher):
    async with session_maker() as session:
        assert await repo.account_name_exists(session, account.owner_id, "dk")  # büyük/küçük harf
        session.add(
            Account(
                owner_id=account.owner_id,
                name="DK",
                phone="+1",
                tg_user_id=999,
                session_enc=cipher.encrypt("x"),
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()


async def test_upsert_user_admin_flags(session_maker):
    async with session_maker() as session:
        admin, created = await repo.upsert_user(session, 1, "admin", "Admin", [1])
        stranger, _ = await repo.upsert_user(session, 2, None, "Yabancı", [1])
        await session.commit()
        assert created and admin.has_access
        assert not stranger.has_access
        _, created_again = await repo.upsert_user(session, 1, "yeni_ad", "Admin", [1])
        assert not created_again
        assert (await session.get(User, 1)).username == "yeni_ad"


# --------------------------------------------------------------------------- callback verisi


def test_callback_data_fits_telegram_limit():
    worst = [
        AccountCB(action="delete_yes", aid=2_147_483_647),
        ExceptionCB(action="refresh", aid=2_147_483_647, page=9999, cid=-1_009_999_999_999_999),
        FilterCB(action="cooldown", aid=2_147_483_647, fid=2_147_483_647),
        NumpadCB(key="del"),
    ]
    for data in worst:
        assert len(data.pack().encode()) <= 64, data.pack()


# --------------------------------------------------------------------------- kilitler


async def test_local_lock_is_exclusive():
    first, second = LocalLock("k", 1000), LocalLock("k", 1000)
    assert await first.acquire()
    assert not await second.acquire()
    await first.release()
    assert await second.acquire()
    await second.release()


@pytest.fixture
async def redis():
    client = Redis.from_url(os.getenv("TEST_REDIS_URL", "redis://localhost:6379/15"))
    try:
        await client.ping()
    except Exception:
        await client.aclose()
        pytest.skip("Redis erişilemiyor")
    yield client
    await client.flushdb()
    await client.aclose()


async def test_redis_lock(redis):
    factory = LockFactory(redis, ttl_ms=5000)
    first, second = factory("worker:1"), factory("worker:1")
    assert isinstance(first, RedisLock)
    assert await first.acquire()
    assert not await second.acquire()
    assert await first.extend()
    assert not await second.extend()
    await second.release()  # başkasının kilidini silemez
    assert await redis.exists("tgbt:lock:worker:1")
    await first.release()
    assert await second.acquire()
    await second.release()
