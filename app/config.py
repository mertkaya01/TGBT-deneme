"""Uygulama ayarları (.env / ortam değişkenleri)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///data/bot.db"


class DatabaseSettings(BaseSettings):
    """Sadece veritabanı adresi; Alembic bot token'ı olmadan da çalışabilsin diye ayrı."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = DEFAULT_DATABASE_URL


class Settings(DatabaseSettings):
    # --- Zorunlu ---
    bot_token: SecretStr
    api_id: int
    api_hash: SecretStr
    session_encryption_key: SecretStr = Field(
        description="Fernet anahtarı; userbot oturumlarını DB'de şifreler."
    )

    # --- Altyapı ---
    redis_url: str | None = None
    auto_migrate: bool = True
    data_dir: Path = Path("data")
    log_level: str = "INFO"
    timezone: str = "Europe/Istanbul"

    # --- Erişim ---
    admin_ids: Annotated[list[int], NoDecode] = Field(default_factory=list)
    max_accounts_per_user: int = 5

    # --- Userbot istemcisi ---
    device_model: str = "TGBT Controller"
    system_version: str = "Linux"
    app_version: str = "1.0"
    lang_code: str = "tr"
    flood_sleep_threshold: int = 60
    long_flood_notify_sec: int = 600
    login_timeout_sec: int = 600
    login_attempts_per_hour: int = 5

    # --- Gönderim ---
    min_cycle_minutes: int = 1
    max_cycle_minutes: int = 10080
    spam_warning_cycle_minutes: int = 10
    max_batch_size: int = 20
    dm_broadcast_min_delay: float = 1.5
    dm_broadcast_max_delay: float = 3.5

    @field_validator("admin_ids", mode="before")
    @classmethod
    def _split_admin_ids(cls, value: object) -> object:
        if isinstance(value, str):
            return [int(part) for part in value.replace(";", ",").split(",") if part.strip()]
        if isinstance(value, int):
            return [value]
        return value

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
