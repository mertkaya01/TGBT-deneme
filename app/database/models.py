"""Veritabanı modelleri."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, UTCDateTime


def utcnow() -> datetime:
    return datetime.now(UTC)


def _enum(enum_cls: type[StrEnum]) -> Enum:
    # native_enum=False: PostgreSQL'de ENUM yerine VARCHAR; yeni değer migration istemez.
    return Enum(
        enum_cls,
        native_enum=False,
        length=24,
        values_callable=lambda members: [m.value for m in members],
        validate_strings=True,
    )


class AccountStatus(StrEnum):
    ACTIVE = "active"
    AUTH_ERROR = "auth_error"  # oturum düştü / iptal edildi
    SPAM_LIMITED = "spam_limited"  # PeerFlood: Telegram spam kısıtı
    DISABLED = "disabled"


class ContentType(StrEnum):
    TEXT = "text"
    PHOTO = "photo"
    FORWARD = "forward"


class MatchType(StrEnum):
    CONTAINS = "contains"  # mesajın içinde geçerse
    EXACT = "exact"  # mesaj tamamen eşitse
    WORD = "word"  # ayrı bir kelime olarak geçerse


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class User(TimestampMixin, Base):
    """Controller bot kullanıcısı (Telegram kullanıcı kimliği birincil anahtardır)."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    username: Mapped[str | None] = mapped_column(String(64))
    full_name: Mapped[str] = mapped_column(String(256), default="")
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False)
    max_accounts: Mapped[int | None] = mapped_column(Integer)  # None → ayarlardaki varsayılan

    accounts: Mapped[list[Account]] = relationship(
        back_populates="owner", cascade="all, delete-orphan", passive_deletes=True, lazy="raise"
    )

    @property
    def has_access(self) -> bool:
        return not self.is_banned and (self.is_admin or self.is_allowed)


class Account(TimestampMixin, Base):
    """Userbot slotu: kullanıcının bağladığı bir Telegram hesabı."""

    __tablename__ = "accounts"
    __table_args__ = (UniqueConstraint("owner_id", "name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(32))
    phone: Mapped[str] = mapped_column(String(20))
    tg_user_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    tg_username: Mapped[str | None] = mapped_column(String(64))
    tg_first_name: Mapped[str] = mapped_column(String(128), default="")
    session_enc: Mapped[str] = mapped_column(Text)
    status: Mapped[AccountStatus] = mapped_column(
        _enum(AccountStatus), default=AccountStatus.ACTIVE
    )
    auto_message_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    dm_auto_reply_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    last_error: Mapped[str | None] = mapped_column(Text)

    owner: Mapped[User] = relationship(back_populates="accounts", lazy="raise")
    auto_config: Mapped[AutoMessageConfig] = relationship(
        back_populates="account",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
        lazy="selectin",
    )
    dm_config: Mapped[DMAutoReplyConfig] = relationship(
        back_populates="account",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
        lazy="selectin",
    )
    exception_chats: Mapped[list[ExceptionChat]] = relationship(
        back_populates="account", cascade="all, delete-orphan", passive_deletes=True, lazy="raise"
    )
    reply_filters: Mapped[list[ReplyFilter]] = relationship(
        back_populates="account", cascade="all, delete-orphan", passive_deletes=True, lazy="raise"
    )


class AutoMessageConfig(Base):
    """Otomatik mesaj içeriği, zamanlama ve döngü istatistikleri (hesap başına bir tane)."""

    __tablename__ = "auto_message_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), unique=True
    )

    # --- İçerik ---
    content_type: Mapped[ContentType] = mapped_column(_enum(ContentType), default=ContentType.TEXT)
    text: Mapped[str] = mapped_column(Text, default="")
    entities: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    photo_path: Mapped[str | None] = mapped_column(String(512))
    source_peer: Mapped[str | None] = mapped_column(String(128))  # '@kanal' veya '-100…'
    source_msg_id: Mapped[int | None] = mapped_column(Integer)
    source_link: Mapped[str | None] = mapped_column(String(256))
    hide_forward_source: Mapped[bool] = mapped_column(Boolean, default=False)

    # --- Kişi paylaşma ---
    contact_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    contact_phone: Mapped[str | None] = mapped_column(String(32))
    contact_first_name: Mapped[str | None] = mapped_column(String(128))
    contact_last_name: Mapped[str | None] = mapped_column(String(128))

    # --- Davranış ---
    text_fallback_on_media_forbidden: Mapped[bool] = mapped_column(Boolean, default=True)
    include_archived: Mapped[bool] = mapped_column(Boolean, default=False)

    # --- Zamanlama ---
    batch_size: Mapped[int] = mapped_column(Integer, default=3)
    min_delay_sec: Mapped[float] = mapped_column(Float, default=0.0)
    max_delay_sec: Mapped[float] = mapped_column(Float, default=5.0)
    cycle_minutes: Mapped[int] = mapped_column(Integer, default=60)

    # --- İstatistik ---
    last_cycle_started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_cycle_finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    next_cycle_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_cycle_targets: Mapped[int] = mapped_column(Integer, default=0)
    last_cycle_sent: Mapped[int] = mapped_column(Integer, default=0)
    last_cycle_failed: Mapped[int] = mapped_column(Integer, default=0)
    last_cycle_skipped: Mapped[int] = mapped_column(Integer, default=0)
    total_sent: Mapped[int] = mapped_column(BigInteger, default=0)

    account: Mapped[Account] = relationship(back_populates="auto_config", lazy="raise")

    @property
    def is_configured(self) -> bool:
        if self.content_type == ContentType.TEXT:
            return bool(self.text.strip())
        if self.content_type == ContentType.PHOTO:
            return bool(self.photo_path)
        return bool(self.source_peer and self.source_msg_id)

    @property
    def has_contact(self) -> bool:
        return bool(self.contact_enabled and self.contact_phone)


class ExceptionChat(Base):
    """Otomatik mesaj ve yanıt filtrelerinin uygulanmayacağı sohbet."""

    __tablename__ = "exception_chats"
    __table_args__ = (UniqueConstraint("account_id", "chat_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    chat_id: Mapped[int] = mapped_column(BigInteger)  # Bot API biçiminde (-100…)
    title: Mapped[str] = mapped_column(String(256), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    account: Mapped[Account] = relationship(back_populates="exception_chats", lazy="raise")


class DMAutoReplyConfig(Base):
    """Hesaba özelden ilk kez yazanlara gönderilecek otomatik cevap."""

    __tablename__ = "dm_auto_reply_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), unique=True
    )
    text: Mapped[str] = mapped_column(Text, default="")
    entities: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    photo_path: Mapped[str | None] = mapped_column(String(512))
    skip_contacts: Mapped[bool] = mapped_column(Boolean, default=False)

    account: Mapped[Account] = relationship(back_populates="dm_config", lazy="raise")

    @property
    def is_configured(self) -> bool:
        return bool(self.text.strip() or self.photo_path)


class DMRepliedUser(Base):
    """Oto-cevap gönderilmiş (veya zaten tanıdık olan) kişiler; ikinci kez cevap verilmez."""

    __tablename__ = "dm_replied_users"
    __table_args__ = (UniqueConstraint("account_id", "peer_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    peer_id: Mapped[int] = mapped_column(BigInteger)
    replied: Mapped[bool] = mapped_column(Boolean, default=True)  # False: eski tanıdık, cevap yok
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class ReplyFilter(Base):
    """Gruplarda belirli kelimeler yazıldığında verilecek otomatik yanıt."""

    __tablename__ = "reply_filters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    keywords: Mapped[list[str]] = mapped_column(JSON, default=list)  # normalize edilmiş
    match_type: Mapped[MatchType] = mapped_column(_enum(MatchType), default=MatchType.CONTAINS)
    reply_text: Mapped[str] = mapped_column(Text)
    reply_entities: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    cooldown_sec: Mapped[int] = mapped_column(Integer, default=60)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    account: Mapped[Account] = relationship(back_populates="reply_filters", lazy="raise")
