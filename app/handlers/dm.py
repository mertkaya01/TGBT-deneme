"""DM'deki herkese toplu mesaj ve DM oto-cevap ayarları."""

from __future__ import annotations

import contextlib
import time

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app import texts
from app.config import Settings
from app.database import repositories as repo
from app.database.models import Account, ContentType, User
from app.handlers.common import (
    answer_not_found,
    cleanup_state,
    download_photo,
    edit_or_send,
    get_account,
    remove_file,
)
from app.keyboards import inline
from app.keyboards.callbacks import AccountCB, DmCB
from app.states.states import DMStates
from app.userbots.broadcast import BroadcastProgress
from app.userbots.sender import OutgoingContent
from app.userbots.userbot_manager import UserbotManager
from app.utils.entities import serialize_entities

router = Router(name="dm")

PROGRESS_EDIT_INTERVAL = 3.0


async def _content_from_message(
    message: Message, bot: Bot, settings: Settings, aid: int, prefix: str
) -> dict | None:
    if message.photo:
        return {
            "text": message.caption or "",
            "entities": serialize_entities(message.caption_entities),
            "photo": await download_photo(bot, message, settings, aid, prefix),
        }
    if message.text:
        return {
            "text": message.text,
            "entities": serialize_entities(message.entities),
            "photo": None,
        }
    return None


# =========================================================================== toplu gönderim


@router.callback_query(AccountCB.filter(F.action == "dm_all"))
async def broadcast_start(
    callback: CallbackQuery,
    callback_data: AccountCB,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    manager: UserbotManager,
) -> None:
    account = await get_account(session, db_user, callback_data.aid)
    if account is None:
        await answer_not_found(callback)
        return
    runtime = manager.get_runtime(account.id)
    if runtime is None:
        await callback.answer(texts.NOT_CONNECTED, show_alert=True)
        return
    if runtime.broadcast_running:
        await callback.answer(texts.BROADCAST_RUNNING, show_alert=True)
        return
    await cleanup_state(state)
    await callback.answer()
    await edit_or_send(callback, texts.DM_SCANNING)
    count = await manager.count_dm_targets(account.id)
    if count == 0:
        await edit_or_send(callback, texts.BROADCAST_EMPTY, inline.back_to_panel(account.id))
        return
    await state.set_state(DMStates.broadcast_message)
    await state.update_data(aid=account.id)
    await edit_or_send(
        callback, texts.ASK_BROADCAST.format(count=count), inline.cancel_flow(account.id)
    )


@router.message(DMStates.broadcast_message)
async def broadcast_message(
    message: Message,
    state: FSMContext,
    manager: UserbotManager,
    settings: Settings,
    bot: Bot,
) -> None:
    data = await state.get_data()
    aid: int = data["aid"]
    content = await _content_from_message(message, bot, settings, aid, "dm_bc")
    if content is None:
        await message.answer(texts.UNSUPPORTED_CONTENT)
        return
    remove_file((data.get("bc") or {}).get("photo"))
    count = await manager.count_dm_targets(aid)
    await state.update_data(bc=content)
    await state.set_state(DMStates.broadcast_confirm)
    await message.reply(
        texts.BROADCAST_CONFIRM.format(count=count), reply_markup=inline.broadcast_confirm(aid)
    )


@router.callback_query(DMStates.broadcast_confirm, DmCB.filter(F.action == "go"))
async def broadcast_go(
    callback: CallbackQuery,
    callback_data: DmCB,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    manager: UserbotManager,
    bot: Bot,
) -> None:
    account = await get_account(session, db_user, callback_data.aid)
    if account is None:
        await answer_not_found(callback)
        return
    data = await state.get_data()
    await state.clear()  # fotoğraf dosyası gönderim bitince silinir
    bc: dict = data["bc"]
    content = OutgoingContent(
        content_type=ContentType.PHOTO if bc.get("photo") else ContentType.TEXT,
        text=bc.get("text", ""),
        entities=bc.get("entities", []),
        photo_path=bc.get("photo"),
    )
    assert isinstance(callback.message, Message)
    chat_id, message_id = callback.message.chat.id, callback.message.message_id
    name = texts.html(account.name)
    last_edit = 0.0

    async def on_progress(progress: BroadcastProgress) -> None:
        nonlocal last_edit
        now = time.monotonic()
        if not progress.finished and now - last_edit < PROGRESS_EDIT_INTERVAL:
            return
        last_edit = now
        fields = {
            "name": name,
            "total": progress.total,
            "sent": progress.sent,
            "failed": progress.failed,
            "done": progress.done,
        }
        if not progress.finished:
            text, markup = (
                texts.BROADCAST_PROGRESS.format(**fields),
                inline.broadcast_running(account.id),
            )
        else:
            remove_file(content.photo_path)
            markup = inline.back_to_panel(account.id)
            if progress.abort_reason:
                text = texts.BROADCAST_ABORTED.format(
                    reason=texts.html(progress.abort_reason), **fields
                )
            elif progress.cancelled:
                text = texts.BROADCAST_CANCELLED.format(**fields)
            else:
                text = texts.BROADCAST_DONE.format(**fields)
        with contextlib.suppress(TelegramBadRequest):
            await bot.edit_message_text(
                text, chat_id=chat_id, message_id=message_id, reply_markup=markup
            )

    try:
        job = await manager.start_broadcast(account.id, content, on_progress)
    except RuntimeError as exc:
        remove_file(content.photo_path)
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer()
    await on_progress(job.progress)


@router.callback_query(DmCB.filter(F.action == "stop"))
async def broadcast_stop(
    callback: CallbackQuery,
    callback_data: DmCB,
    session: AsyncSession,
    db_user: User,
    manager: UserbotManager,
) -> None:
    if await get_account(session, db_user, callback_data.aid) is None:
        await answer_not_found(callback)
        return
    stopped = manager.cancel_broadcast(callback_data.aid)
    await callback.answer("⏹ Durduruluyor…" if stopped else "Çalışan gönderim yok.")


# =========================================================================== DM oto-cevap ayarları


async def _show_dm_settings(
    target: CallbackQuery | Message, session: AsyncSession, account: Account
) -> None:
    dm = account.dm_config
    replied = await repo.count_replied(session, account.id)
    if dm.is_configured:
        preview = texts.html(dm.text[:600]) or "—"
        if dm.photo_path:
            preview = "🖼 <i>fotoğraf</i>\n" + preview
    else:
        preview = texts.CONTENT_NONE
    text = texts.DM_SETTINGS.format(
        name=texts.html(account.name),
        state=texts.on_off(account.dm_auto_reply_enabled),
        contacts=texts.on_off(not dm.skip_contacts),
        replied=replied,
        preview=preview,
    )
    await edit_or_send(target, text, inline.dm_settings(account, dm))


@router.callback_query(AccountCB.filter(F.action == "dm_cfg"))
async def dm_settings(
    callback: CallbackQuery,
    callback_data: AccountCB,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
) -> None:
    await cleanup_state(state)
    account = await get_account(session, db_user, callback_data.aid)
    if account is None:
        await answer_not_found(callback)
        return
    await _show_dm_settings(callback, session, account)
    await callback.answer()


@router.callback_query(DmCB.filter(F.action == "toggle"))
async def dm_toggle(
    callback: CallbackQuery,
    callback_data: DmCB,
    session: AsyncSession,
    db_user: User,
    manager: UserbotManager,
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
    await _show_dm_settings(callback, session, account)


@router.callback_query(DmCB.filter(F.action == "contacts"))
async def dm_toggle_contacts(
    callback: CallbackQuery,
    callback_data: DmCB,
    session: AsyncSession,
    db_user: User,
    manager: UserbotManager,
) -> None:
    account = await get_account(session, db_user, callback_data.aid)
    if account is None:
        await answer_not_found(callback)
        return
    account.dm_config.skip_contacts = not account.dm_config.skip_contacts
    await session.commit()
    await manager.refresh_settings(account.id)
    await callback.answer()
    await _show_dm_settings(callback, session, account)


@router.callback_query(DmCB.filter(F.action == "set"))
async def dm_set_prompt(
    callback: CallbackQuery,
    callback_data: DmCB,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
) -> None:
    if await get_account(session, db_user, callback_data.aid) is None:
        await answer_not_found(callback)
        return
    await state.set_state(DMStates.reply_message)
    await state.update_data(aid=callback_data.aid)
    await edit_or_send(callback, texts.ASK_DM_REPLY, inline.cancel_flow(callback_data.aid))
    await callback.answer()


@router.message(DMStates.reply_message)
async def dm_reply_received(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    manager: UserbotManager,
    settings: Settings,
    bot: Bot,
) -> None:
    data = await state.get_data()
    account = await get_account(session, db_user, data["aid"])
    if account is None:
        await state.clear()
        await message.answer(texts.ACCOUNT_NOT_FOUND)
        return
    content = await _content_from_message(message, bot, settings, account.id, "dm_reply")
    if content is None:
        await message.answer(texts.UNSUPPORTED_CONTENT)
        return
    await state.clear()
    dm = account.dm_config
    old_photo = dm.photo_path
    dm.text, dm.entities, dm.photo_path = content["text"], content["entities"], content["photo"]
    await session.commit()
    if old_photo and old_photo != dm.photo_path:
        remove_file(old_photo)
    await manager.refresh_settings(account.id)
    await message.answer(texts.DM_REPLY_SAVED)
    await _show_dm_settings(message, session, account)
