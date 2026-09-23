"""Telethon hatalarının ne yapılacağına göre sınıflandırılması."""

from __future__ import annotations

from enum import StrEnum

from telethon import errors


class ErrorAction(StrEnum):
    FLOOD = "flood"  # hesap genelinde bekle, sonra tekrar dene
    SLOW_MODE = "slow_mode"  # bu sohbeti belirtilen süre boyunca atla
    MEDIA_FORBIDDEN = "media_forbidden"  # sadece metinle tekrar dene
    SKIP_CHAT = "skip_chat"  # bu sohbete yazılamıyor, geç
    ACCOUNT_LIMITED = "account_limited"  # PeerFlood: spam kısıtı, döngüyü durdur
    SESSION_DEAD = "session_dead"  # oturum geçersiz, istemciyi kapat
    UNKNOWN = "unknown"


class AccountLimitedError(Exception):
    """Hesap Telegram tarafından spam kısıtına alındı (PeerFlood)."""


class SessionDeadError(Exception):
    """Oturum sonlandırılmış veya hesap silinmiş."""


_MEDIA_FORBIDDEN = (
    errors.ChatSendMediaForbiddenError,
    errors.ChatSendPhotosForbiddenError,
    errors.ChatForwardsRestrictedError,
    errors.ChatSendGifsForbiddenError,
)
_SESSION_DEAD = (
    errors.AuthKeyUnregisteredError,
    errors.AuthKeyDuplicatedError,
    errors.SessionRevokedError,
    errors.SessionExpiredError,
    errors.UserDeactivatedError,
    errors.UserDeactivatedBanError,
    errors.UnauthorizedError,
)
_SKIP_CHAT = (
    errors.ChatWriteForbiddenError,
    errors.UserBannedInChannelError,
    errors.ChannelPrivateError,
    errors.ChatAdminRequiredError,
    errors.ChatRestrictedError,
    errors.ChatSendPlainForbiddenError,
    errors.ChatGuestSendForbiddenError,
    errors.ChannelInvalidError,
    errors.ChatIdInvalidError,
    errors.PeerIdInvalidError,
    errors.UserIsBlockedError,
    errors.InputUserDeactivatedError,
    errors.YouBlockedUserError,
    errors.ForbiddenError,
    errors.BadRequestError,
)


def classify(exc: BaseException) -> ErrorAction:
    # Sıra önemli: özel sınıflar, genel üst sınıflarından (BadRequest/Forbidden) önce gelir.
    if isinstance(exc, errors.SlowModeWaitError):
        return ErrorAction.SLOW_MODE
    if isinstance(exc, errors.FloodError) and hasattr(exc, "seconds"):
        return ErrorAction.FLOOD
    if isinstance(exc, errors.PeerFloodError):
        return ErrorAction.ACCOUNT_LIMITED
    if isinstance(exc, _MEDIA_FORBIDDEN):
        return ErrorAction.MEDIA_FORBIDDEN
    if isinstance(exc, _SESSION_DEAD):
        return ErrorAction.SESSION_DEAD
    if isinstance(exc, _SKIP_CHAT):
        return ErrorAction.SKIP_CHAT
    return ErrorAction.UNKNOWN


def wait_seconds(exc: BaseException) -> int:
    return int(getattr(exc, "seconds", 0) or 0)
