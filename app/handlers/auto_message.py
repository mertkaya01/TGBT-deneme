"""Otomatik mesaj ayarlama sihirbazı: içerik → 3'lü gruplar arası bekleme (sn) → döngü (dk)."""

from __future__ import annotations

from typing import Any

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, MessageOriginChannel
from sqlalchemy.ext.asyncio import AsyncSession

from app import texts
from app.config import Settings
from app.database.models import ContentType, User
from app.handlers.common import (
    answer_not_found,
    auto_summary,
    cleanup_state,
    download_photo,
    edit_or_send,
    get_account,
    remove_file,
    show_panel,
)
from app.keyboards import inline
from app.keyboards.callbacks import AccountCB
from app.states.states import AutoMsgStates
from app.userbots.sender import SourceUnavailableError
from app.userbots.userbot_manager import UserbotManager
from app.utils.entities import serialize_entities
from app.utils.text import parse_delay_range, parse_int, parse_post_link

router = Router(name="auto_message")


@router.callback_query(AccountCB.filter(F.action == "auto_cfg"))
async def start_wizard(
    callback: CallbackQuery,
    callback_data: AccountCB,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    settings: Settings,
) -> None:
    account = await get_account(session, db_user, callback_data.aid)
    if account is None:
        await answer_not_found(callback)
        return
    await cleanup_state(state)
    await state.set_state(AutoMsgStates.message)
    await state.update_data(aid=account.id)
    await edit_or_send(callback, auto_summary(account, settings))
    assert isinstance(callback.message, Message)
    await callback.message.answer(
        texts.ASK_AUTO_MESSAGE, reply_markup=inline.cancel_flow(account.id)
    )
    await callback.answer()


def _channel_post(origin: MessageOriginChannel) -> dict[str, Any]:
    chat = origin.chat
    if chat.username:
        peer, link = f"@{chat.username}", f"https://t.me/{chat.username}/{origin.message_id}"
    else:
        internal_id = str(chat.id).removeprefix("-100")
        peer, link = str(chat.id), f"https://t.me/c/{internal_id}/{origin.message_id}"
    return {
        "type": ContentType.FORWARD.value,
        "peer": peer,
        "msg_id": origin.message_id,
        "link": link,
    }


@router.message(AutoMsgStates.message)
async def on_content(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    manager: UserbotManager,
    settings: Settings,
    bot: Bot,
) -> None:
    data = await state.get_data()
    aid: int = data["aid"]
    if await get_account(session, db_user, aid) is None:
        await cleanup_state(state)
        await message.answer(texts.ACCOUNT_NOT_FOUND)
        return

    post_link = parse_post_link(message.text) if message.text else None
    if isinstance(message.forward_origin, MessageOriginChannel):
        pending = _channel_post(message.forward_origin)
    elif post_link is not None:
        pending = {
            "type": ContentType.FORWARD.value,
            "peer": post_link.peer,
            "msg_id": post_link.message_id,
            "link": (message.text or "").strip(),
        }
    elif message.photo:
        pending = {
            "type": ContentType.PHOTO.value,
            "text": message.caption or "",
            "entities": serialize_entities(message.caption_entities),
            "photo": await download_photo(bot, message, settings, aid, "auto"),
        }
    elif message.text:
        pending = {
            "type": ContentType.TEXT.value,
            "text": message.text,
            "entities": serialize_entities(message.entities),
        }
    else:
        await message.answer(texts.UNSUPPORTED_CONTENT)
        return

    if pending["type"] == ContentType.FORWARD.value:
        status = await message.answer(texts.CHECKING_SOURCE)
        try:
            await manager.verify_forward_source(aid, pending["peer"], pending["msg_id"])
        except (SourceUnavailableError, RuntimeError) as exc:
            await status.edit_text(texts.SOURCE_ERROR.format(error=texts.html(str(exc))))
            return
        await status.edit_text(texts.FORWARD_ACCEPTED.format(link=texts.html(pending["link"])))

    remove_file((data.get("pending") or {}).get("photo"))  # önceki denemeden kalan dosya
    await state.update_data(pending=pending)
    await state.set_state(AutoMsgStates.delay)
    await message.answer(texts.ASK_DELAY, reply_markup=inline.cancel_flow(aid))


@router.message(AutoMsgStates.delay, F.text)
async def on_delay(message: Message, state: FSMContext) -> None:
    try:
        low, high = parse_delay_range(message.text or "")
    except ValueError:
        await message.answer(texts.INVALID_DELAY)
        return
    data = await state.get_data()
    await state.update_data(delay=[low, high])
    await state.set_state(AutoMsgStates.cycle)
    await message.answer(texts.ASK_CYCLE, reply_markup=inline.cancel_flow(data["aid"]))


@router.message(AutoMsgStates.cycle, F.text)
async def on_cycle(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    manager: UserbotManager,
    settings: Settings,
) -> None:
    try:
        minutes = parse_int(
            message.text or "", settings.min_cycle_minutes, settings.max_cycle_minutes
        )
    except ValueError:
        await message.answer(
            texts.INVALID_CYCLE.format(
                min=settings.min_cycle_minutes, max=settings.max_cycle_minutes
            )
        )
        return

    data = await state.get_data()
    account = await get_account(session, db_user, data["aid"])
    if account is None:
        await cleanup_state(state)
        await message.answer(texts.ACCOUNT_NOT_FOUND)
        return

    cfg = account.auto_config
    pending: dict[str, Any] = data["pending"]
    old_photo = cfg.photo_path
    kind = ContentType(pending["type"])
    cfg.content_type = kind
    cfg.text = pending.get("text", "")
    cfg.entities = pending.get("entities", [])
    cfg.photo_path = pending.get("photo")
    cfg.source_peer = pending.get("peer")
    cfg.source_msg_id = pending.get("msg_id")
    cfg.source_link = pending.get("link")
    cfg.min_delay_sec, cfg.max_delay_sec = data["delay"]
    cfg.cycle_minutes = minutes
    await session.commit()
    await state.clear()
    if old_photo and old_photo != cfg.photo_path:
        remove_file(old_photo)

    restarted = await manager.restart_worker(account.id)
    text = texts.AUTO_SAVED + "\n\n" + auto_summary(account, settings)
    if minutes < settings.spam_warning_cycle_minutes:
        text += texts.SPAM_WARNING.format(minutes=settings.spam_warning_cycle_minutes)
    if restarted:
        text += texts.RESTARTED_NOTE
    await message.answer(text)
    await show_panel(message, account, manager, settings)
