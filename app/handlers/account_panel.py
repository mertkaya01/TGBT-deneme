"""Hesap paneli: aç/kapat toggle'ları, sistem kontrolü ve hesap silme."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app import texts
from app.config import Settings
from app.database.models import AccountStatus, User
from app.handlers.common import (
    answer_not_found,
    cleanup_state,
    edit_or_send,
    get_account,
    show_accounts,
    show_panel,
)
from app.keyboards import inline
from app.keyboards.callbacks import AccountCB
from app.userbots.userbot_manager import HealthReport, UserbotManager
from app.utils.text import format_dt, format_duration

router = Router(name="account_panel")

STATUS_NAMES = {
    AccountStatus.ACTIVE: "Aktif",
    AccountStatus.AUTH_ERROR: "⚠️ Oturum geçersiz",
    AccountStatus.SPAM_LIMITED: "🚫 Spam kısıtı",
    AccountStatus.DISABLED: "Devre dışı",
}


@router.callback_query(AccountCB.filter(F.action == "open"))
async def open_panel(
    callback: CallbackQuery,
    callback_data: AccountCB,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    manager: UserbotManager,
    settings: Settings,
) -> None:
    await cleanup_state(state)
    account = await get_account(session, db_user, callback_data.aid)
    if account is None:
        await answer_not_found(callback)
        return
    await show_panel(callback, account, manager, settings)
    await callback.answer()


@router.callback_query(AccountCB.filter(F.action == "auto"))
async def toggle_auto_message(
    callback: CallbackQuery,
    callback_data: AccountCB,
    session: AsyncSession,
    db_user: User,
    manager: UserbotManager,
    settings: Settings,
) -> None:
    account = await get_account(session, db_user, callback_data.aid)
    if account is None:
        await answer_not_found(callback)
        return
    enable = not account.auto_message_enabled
    if enable:
        if account.status == AccountStatus.AUTH_ERROR:
            await callback.answer(texts.STATUS_AUTH_ERROR, show_alert=True)
            return
        if not account.auto_config.is_configured:
            await callback.answer(texts.AUTO_NOT_CONFIGURED, show_alert=True)
            return
        if not manager.is_connected(account.id):
            await callback.answer(texts.NOT_CONNECTED, show_alert=True)
            return

    await manager.set_auto_message(account.id, enable)
    await session.refresh(account)
    await session.refresh(account.auto_config)
    template = texts.AUTO_STARTED if enable else texts.AUTO_STOPPED
    await callback.answer(template.format(name=account.name))
    await show_panel(callback, account, manager, settings)


@router.callback_query(AccountCB.filter(F.action == "dm_toggle"))
async def toggle_dm_reply(
    callback: CallbackQuery,
    callback_data: AccountCB,
    session: AsyncSession,
    db_user: User,
    manager: UserbotManager,
    settings: Settings,
) -> None:
    account = await get_account(session, db_user, callback_data.aid)
    if account is None:
        await answer_not_found(callback)
        return
    enable = not account.dm_auto_reply_enabled
    if enable and not account.dm_config.is_configured:
        await callback.answer(texts.DM_REPLY_NOT_CONFIGURED, show_alert=True)
        return
    await manager.set_dm_auto_reply(account.id, enable)
    await session.refresh(account)
    template = texts.DM_REPLY_ENABLED if enable else texts.DM_REPLY_DISABLED
    await callback.answer(template.format(name=account.name))
    await show_panel(callback, account, manager, settings)


# --------------------------------------------------------------------------- sistem kontrolü


def _health_text(name: str, report: HealthReport, account, settings: Settings) -> str:
    cfg = account.auto_config
    return texts.HEALTH_REPORT.format(
        name=texts.html(name),
        connected=texts.YES if report.connected else texts.NO,
        authorized=texts.YES if report.authorized else texts.NO,
        me=texts.html(report.me),
        ping=f"{report.ping_ms} ms" if report.ping_ms is not None else "—",
        status=STATUS_NAMES.get(report.status, report.status)
        + (
            f"\n⚠️ Son hata: <code>{texts.html(report.last_error[:200])}</code>"
            if report.last_error
            else ""
        ),
        worker="🟢 çalışıyor" if report.worker_running else "⚪ kapalı",
        last_cycle=format_dt(cfg.last_cycle_finished_at, settings.tz),
        sent=cfg.last_cycle_sent,
        failed=cfg.last_cycle_failed,
        skipped=cfg.last_cycle_skipped,
        targets=cfg.last_cycle_targets,
        next_cycle=format_dt(cfg.next_cycle_at, settings.tz) if report.worker_running else "—",
        flood=format_duration(report.flood_remaining) if report.flood_remaining else "yok",
        groups=report.groups if report.groups is not None else "—",
        exceptions=report.exceptions,
        filters=report.filters,
        dm=texts.on_off(report.dm_auto_reply),
        broadcast="🟢 çalışıyor" if report.broadcast_running else "—",
    )


@router.callback_query(AccountCB.filter(F.action == "health"))
async def health(
    callback: CallbackQuery,
    callback_data: AccountCB,
    session: AsyncSession,
    db_user: User,
    manager: UserbotManager,
    settings: Settings,
) -> None:
    account = await get_account(session, db_user, callback_data.aid)
    if account is None:
        await answer_not_found(callback)
        return
    await callback.answer(texts.HEALTH_CHECKING)
    report = await manager.health_check(account.id)
    await session.refresh(account)
    await session.refresh(account.auto_config)
    await edit_or_send(
        callback,
        _health_text(account.name, report, account, settings),
        inline.health_menu(account.id),
    )


@router.callback_query(AccountCB.filter(F.action == "reconnect"))
async def reconnect(
    callback: CallbackQuery,
    callback_data: AccountCB,
    session: AsyncSession,
    db_user: User,
    manager: UserbotManager,
    settings: Settings,
) -> None:
    account = await get_account(session, db_user, callback_data.aid)
    if account is None:
        await answer_not_found(callback)
        return
    runtime = await manager.reconnect(account.id)
    if runtime is None:
        await session.refresh(account)
        error = account.last_error or "bağlantı kurulamadı"
        await callback.answer(texts.RECONNECT_FAILED.format(error=error)[:190], show_alert=True)
        return
    await callback.answer(texts.RECONNECT_OK)
    await health(callback, callback_data, session, db_user, manager, settings)


# --------------------------------------------------------------------------- hesap silme


@router.callback_query(AccountCB.filter(F.action == "delete"))
async def delete_prompt(
    callback: CallbackQuery,
    callback_data: AccountCB,
    session: AsyncSession,
    db_user: User,
) -> None:
    account = await get_account(session, db_user, callback_data.aid)
    if account is None:
        await answer_not_found(callback)
        return
    await edit_or_send(
        callback,
        texts.DELETE_CONFIRM.format(name=texts.html(account.name)),
        inline.delete_confirm(account.id),
    )
    await callback.answer()


@router.callback_query(AccountCB.filter(F.action == "delete_yes"))
async def delete_confirmed(
    callback: CallbackQuery,
    callback_data: AccountCB,
    session: AsyncSession,
    db_user: User,
    manager: UserbotManager,
    settings: Settings,
) -> None:
    account = await get_account(session, db_user, callback_data.aid)
    if account is None:
        await answer_not_found(callback)
        return
    name = account.name
    session.expunge(account)
    await manager.delete_account(account.id)
    await callback.answer(texts.DELETED_TOAST.format(name=name))
    await show_accounts(callback, session, db_user, manager, settings)
