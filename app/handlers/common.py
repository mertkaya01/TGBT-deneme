"""Handler'ların ortak yardımcıları."""

from __future__ import annotations

import contextlib
import logging
import uuid
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app import texts
from app.config import Settings
from app.database import repositories as repo
from app.database.models import Account, AccountStatus, AutoMessageConfig, User
from app.keyboards import inline
from app.userbots.userbot_manager import UserbotManager
from app.utils.text import format_dt, format_seconds_value

log = logging.getLogger(__name__)


def slot_limit(user: User, settings: Settings) -> int:
    return user.max_accounts or settings.max_accounts_per_user


async def get_account(session: AsyncSession, user: User, aid: int) -> Account | None:
    return await repo.get_owned_account(session, aid, user.id)


async def answer_not_found(callback: CallbackQuery) -> None:
    await callback.answer(texts.ACCOUNT_NOT_FOUND, show_alert=True)


async def edit_or_send(
    target: CallbackQuery | Message,
    text: str,
    markup: InlineKeyboardMarkup | None = None,
) -> Message | None:
    """Callback'ten geliyorsa mesajı düzenler; düzenlenemiyorsa yeni mesaj gönderir."""
    if isinstance(target, CallbackQuery):
        message = target.message
        if isinstance(message, Message):
            try:
                edited = await message.edit_text(text, reply_markup=markup)
                return edited if isinstance(edited, Message) else message
            except TelegramBadRequest as exc:
                if "message is not modified" in str(exc):
                    return message
            return await message.answer(text, reply_markup=markup)
        return None
    return await target.answer(text, reply_markup=markup)


# --------------------------------------------------------------------------- hesap listesi


def account_state(account: Account, connected: bool) -> str:
    """Özet sayaçları için: running | stopped | problem."""
    if account.status in (AccountStatus.AUTH_ERROR, AccountStatus.SPAM_LIMITED) or not connected:
        return "problem"
    return "running" if account.auto_message_enabled else "stopped"


async def show_accounts(
    target: CallbackQuery | Message,
    session: AsyncSession,
    user: User,
    manager: UserbotManager,
    settings: Settings,
    *,
    page: int = 0,
    focus_aid: int = 0,
) -> None:
    accounts = await repo.list_accounts(session, user.id)
    rows = [(a, manager.is_connected(a.id)) for a in accounts]
    if focus_aid:  # panelden dönüşte hesabın bulunduğu sayfayı aç
        index = next((i for i, (a, _) in enumerate(rows) if a.id == focus_aid), 0)
        page = index // inline.ACCOUNTS_PAGE_SIZE
    pages = inline.page_count(len(rows), inline.ACCOUNTS_PAGE_SIZE)
    page = min(max(page, 0), pages - 1)

    counts = {"running": 0, "stopped": 0, "problem": 0}
    for account, connected in rows:
        counts[account_state(account, connected)] += 1
    text = texts.ACCOUNTS_TITLE.format(
        count=len(rows),
        limit=slot_limit(user, settings),
        page_info=texts.ACCOUNTS_PAGE_INFO.format(page=page + 1, pages=pages) if pages > 1 else "",
        search_hint=texts.ACCOUNTS_SEARCH_HINT if pages > 1 else "",
        **counts,
    )
    await edit_or_send(target, text, inline.accounts_menu(rows, page))


# --------------------------------------------------------------------------- hesap paneli


def panel_text(account: Account, manager: UserbotManager, settings: Settings) -> str:
    cfg = account.auto_config
    if account.status == AccountStatus.AUTH_ERROR:
        status = texts.STATUS_AUTH_ERROR
    elif account.status == AccountStatus.SPAM_LIMITED:
        status = texts.STATUS_SPAM
    elif not manager.is_connected(account.id):
        status = texts.STATUS_DISCONNECTED
    elif account.auto_message_enabled:
        status = texts.STATUS_RUNNING
    else:
        status = texts.STATUS_STOPPED
    last = f"{cfg.last_cycle_sent}/{cfg.last_cycle_targets}" if cfg.last_cycle_finished_at else "—"
    next_run = format_dt(cfg.next_cycle_at, settings.tz) if account.auto_message_enabled else "—"
    return texts.PANEL_TITLE.format(name=texts.html(account.name)) + texts.PANEL_STATUS.format(
        status_line=status, last=last, next=next_run
    )


async def show_panel(
    target: CallbackQuery | Message,
    account: Account,
    manager: UserbotManager,
    settings: Settings,
) -> None:
    await edit_or_send(
        target, panel_text(account, manager, settings), inline.account_panel(account)
    )


# --------------------------------------------------------------------------- içerik özeti


def content_summary(cfg: AutoMessageConfig) -> str:
    if not cfg.is_configured:
        return texts.CONTENT_NONE
    preview = texts.html(" ".join(cfg.text.split())[:120]) or "—"
    if cfg.content_type == "photo":
        return texts.CONTENT_PHOTO.format(preview=preview)
    if cfg.content_type == "forward":
        return texts.CONTENT_FORWARD.format(
            link=texts.html(cfg.source_link or cfg.source_peer or ""),
            hidden=" (başlıksız)" if cfg.hide_forward_source else "",
        )
    return texts.CONTENT_TEXT.format(preview=preview)


# --------------------------------------------------------------------------- medya


async def download_photo(
    bot: Bot, message: Message, settings: Settings, aid: int, prefix: str
) -> str:
    """Mesajdaki en büyük fotoğrafı data/media/{aid}/ altına indirir, yolu döndürür."""
    assert message.photo
    directory = settings.media_dir / str(aid)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{prefix}_{uuid.uuid4().hex[:12]}.jpg"
    await bot.download(message.photo[-1], destination=path)
    return str(path)


def remove_file(path: str | None) -> None:
    if path:
        with contextlib.suppress(OSError):
            Path(path).unlink(missing_ok=True)


async def delete_quietly(message: Message) -> None:
    with contextlib.suppress(Exception):
        await message.delete()


async def cleanup_state(state: FSMContext) -> dict:
    """FSM verisindeki yarım kalmış (kaydedilmemiş) medya dosyalarını siler ve durumu temizler."""
    data = await state.get_data()
    pending = data.get("pending") or {}
    remove_file(pending.get("photo"))
    remove_file((data.get("bc") or {}).get("photo"))
    await state.clear()
    return data


def auto_summary(account: Account, settings: Settings) -> str:
    cfg = account.auto_config
    contact = (
        texts.html(f"{cfg.contact_first_name or ''} {cfg.contact_last_name or ''}".strip())
        if cfg.has_contact
        else texts.STATE_OFF
    )
    last = "—"
    if cfg.last_cycle_finished_at:
        finished = format_dt(cfg.last_cycle_finished_at, settings.tz)
        last = f"{cfg.last_cycle_sent}/{cfg.last_cycle_targets} ({finished})"
    return texts.AUTO_SUMMARY.format(
        name=texts.html(account.name),
        content=content_summary(cfg),
        delay=f"{format_seconds_value(cfg.min_delay_sec)}-{format_seconds_value(cfg.max_delay_sec)}",
        batch=cfg.batch_size,
        cycle=cfg.cycle_minutes,
        archived=texts.on_off(cfg.include_archived),
        contact=contact,
        last=last,
        total=cfg.total_sent,
    )
