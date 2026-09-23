"""Uygulama açılışında Alembic migration'larını çalıştırır."""

from __future__ import annotations

import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _upgrade(database_url: str) -> None:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    # Uygulamanın log ayarlarını ezmesin.
    config.attributes["configure_logger"] = False
    command.upgrade(config, "head")


async def run_migrations(database_url: str) -> None:
    # env.py kendi event loop'unu açtığı için ayrı bir thread'de çalıştırılır.
    await asyncio.to_thread(_upgrade, database_url)
