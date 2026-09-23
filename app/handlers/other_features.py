"""🔧 Diğer Özellikler: arşiv, medya→metin, forward başlığı, kişi, grup boyutu, önizleme, export."""

from __future__ import annotations

import re
import shutil

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app import texts
from app.config import Settings
from app.database.models import Account, ContentType, User
from app.handlers.common import (
    answer_not_found,
    cleanup_state,
    edit_or_send,
    get_account,
)
from app.keyboards import inline
from app.keyboards.callbacks import OtherCB
from app.states.states import OtherStates
from app.userbots.sender import SourceUnavailableError
from app.userbots.userbot_manager import UserbotManager
from app.utils.entities import to_aiogram_entities
from app.utils.text import normalize_phone, parse_int

router = Router(name="other_features")

_CONTACT_TEXT_RE = re.compile(r"^\s*(\+?[\d\s\-()]{8,20})\s+(.+?)\s*$")


async def _show_menu(target: CallbackQuery | Message, account: Account) -> None:
    await edit_or_send(
        target,
        texts.OTHER_TITLE.format(name=texts.html(account.name)),
        inline.other_menu(account, account.auto_config),
    )


async def _load(
    callback: CallbackQuery, session: AsyncSession, user: User, aid: int
) -> Account | None:
    account = await get_account(session, user, aid)
    if account is None:
        await answer_not_found(callback)
    return account


@router.callback_query(OtherCB.filter(F.action == "menu"))
async def other_menu(
    callback: CallbackQuery,
    callback_data: OtherCB,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
) -> None:
    await cleanup_state(state)
    if account := await _load(callback, session, db_user, callback_data.aid):
        await _show_menu(callback, account)
        await callback.answer()


@router.callback_query(OtherCB.filter(F.action.in_({"archive", "fallback", "fwd_header"})))
async def toggle_option(
    callback: CallbackQuery,
    callback_data: OtherCB,
    session: AsyncSession,
    db_user: User,
) -> None:
    account = await _load(callback, session, db_user, callback_data.aid)
    if account is None:
        return
    cfg = account.auto_config
    if callback_data.action == "archive":
        cfg.include_archived = not cfg.include_archived
        toast = f"📁 Arşiv grupları: {texts.on_off(cfg.include_archived)}"
    elif callback_data.action == "fallback":
        cfg.text_fallback_on_media_forbidden = not cfg.text_fallback_on_media_forbidden
        toast = f"🖼 Medya → Metin: {texts.on_off(cfg.text_fallback_on_media_forbidden)}"
    else:
        cfg.hide_forward_source = not cfg.hide_forward_source
        label = texts.STATE_HIDDEN if cfg.hide_forward_source else texts.STATE_VISIBLE
        toast = f"↗️ Forward başlığı: {label}"
    await session.commit()
    await callback.answer(toast + " (bir sonraki döngüde geçerli)")
    await _show_menu(callback, account)


# --------------------------------------------------------------------------- kişi paylaşma


def _contact_label(account: Account) -> str:
    cfg = account.auto_config
    if not cfg.has_contact:
        return texts.STATE_OFF
    name = f"{cfg.contact_first_name or ''} {cfg.contact_last_name or ''}".strip()
    return f"<b>{texts.html(name)}</b> (<code>{texts.html(cfg.contact_phone)}</code>)"


@router.callback_query(OtherCB.filter(F.action == "contact"))
async def contact_menu(
    callback: CallbackQuery,
    callback_data: OtherCB,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
) -> None:
    await cleanup_state(state)
    if account := await _load(callback, session, db_user, callback_data.aid):
        await edit_or_send(
            callback,
            texts.CONTACT_MENU.format(current=_contact_label(account)),
            inline.contact_menu(account.id, account.auto_config.has_contact),
        )
        await callback.answer()


@router.callback_query(OtherCB.filter(F.action == "contact_set"))
async def contact_set(
    callback: CallbackQuery,
    callback_data: OtherCB,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
) -> None:
    if await _load(callback, session, db_user, callback_data.aid) is None:
        return
    await state.set_state(OtherStates.contact)
    await state.update_data(aid=callback_data.aid)
    await edit_or_send(callback, texts.ASK_CONTACT, inline.cancel_flow(callback_data.aid))
    await callback.answer()


@router.message(OtherStates.contact, F.contact | F.text)
async def contact_received(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
) -> None:
    if message.contact:
        raw = message.contact.phone_number
        phone = normalize_phone(raw if raw.startswith("+") else "+" + raw)
        first, last = message.contact.first_name, message.contact.last_name or ""
    else:
        match = _CONTACT_TEXT_RE.match(message.text or "")
        phone = normalize_phone(match.group(1)) if match else None
        names = match.group(2).split(maxsplit=1) if match else []
        first, last = [*names, "", ""][:2]
    if phone is None or not first:
        await message.answer(texts.INVALID_CONTACT)
        return

    data = await state.get_data()
    account = await get_account(session, db_user, data["aid"])
    await state.clear()
    if account is None:
        await message.answer(texts.ACCOUNT_NOT_FOUND)
        return
    cfg = account.auto_config
    cfg.contact_enabled = True
    cfg.contact_phone = phone
    cfg.contact_first_name = first[:128]
    cfg.contact_last_name = last[:128]
    await session.commit()
    await message.answer(
        texts.CONTACT_SAVED.format(name=texts.html(f"{first} {last}".strip()), phone=phone),
        reply_markup=inline.back_to_other(account.id),
    )


@router.callback_query(OtherCB.filter(F.action == "contact_rm"))
async def contact_remove(
    callback: CallbackQuery,
    callback_data: OtherCB,
    session: AsyncSession,
    db_user: User,
) -> None:
    account = await _load(callback, session, db_user, callback_data.aid)
    if account is None:
        return
    cfg = account.auto_config
    cfg.contact_enabled = False
    cfg.contact_phone = cfg.contact_first_name = cfg.contact_last_name = None
    await session.commit()
    await callback.answer(texts.CONTACT_REMOVED)
    await _show_menu(callback, account)


# --------------------------------------------------------------------------- grup boyutu


@router.callback_query(OtherCB.filter(F.action == "batch"))
async def batch_prompt(
    callback: CallbackQuery,
    callback_data: OtherCB,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    settings: Settings,
) -> None:
    if await _load(callback, session, db_user, callback_data.aid) is None:
        return
    await state.set_state(OtherStates.batch_size)
    await state.update_data(aid=callback_data.aid)
    await edit_or_send(
        callback,
        texts.ASK_BATCH.format(max=settings.max_batch_size),
        inline.cancel_flow(callback_data.aid),
    )
    await callback.answer()


@router.message(OtherStates.batch_size, F.text)
async def batch_received(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    settings: Settings,
) -> None:
    try:
        size = parse_int(message.text or "", 1, settings.max_batch_size)
    except ValueError:
        await message.answer(texts.INVALID_BATCH.format(max=settings.max_batch_size))
        return
    data = await state.get_data()
    account = await get_account(session, db_user, data["aid"])
    await state.clear()
    if account is None:
        await message.answer(texts.ACCOUNT_NOT_FOUND)
        return
    account.auto_config.batch_size = size
    await session.commit()
    await message.answer(
        texts.BATCH_SAVED.format(size=size), reply_markup=inline.back_to_other(account.id)
    )


# --------------------------------------------------------------------------- önizleme


@router.callback_query(OtherCB.filter(F.action == "preview"))
async def preview(
    callback: CallbackQuery,
    callback_data: OtherCB,
    session: AsyncSession,
    db_user: User,
    manager: UserbotManager,
    bot: Bot,
) -> None:
    account = await _load(callback, session, db_user, callback_data.aid)
    if account is None:
        return
    cfg = account.auto_config
    if not cfg.is_configured:
        await callback.answer(texts.PREVIEW_NOT_CONFIGURED, show_alert=True)
        return
    await callback.answer()
    chat_id = callback.from_user.id
    await bot.send_message(chat_id, texts.PREVIEW_HEADER)

    if cfg.content_type == ContentType.TEXT:
        await bot.send_message(
            chat_id, cfg.text, entities=to_aiogram_entities(cfg.entities), parse_mode=None
        )
    elif cfg.content_type == ContentType.PHOTO and cfg.photo_path:
        await bot.send_photo(
            chat_id,
            FSInputFile(cfg.photo_path),
            caption=cfg.text or None,
            caption_entities=to_aiogram_entities(cfg.entities) or None,
            parse_mode=None,
        )
    else:
        mode = "başlıksız olarak" if cfg.hide_forward_source else "kaynak başlığıyla"
        text = texts.PREVIEW_FORWARD.format(link=texts.html(cfg.source_link or ""), mode=mode)
        try:
            source_text = await manager.verify_forward_source(
                account.id, cfg.source_peer or "", cfg.source_msg_id or 0
            )
            if source_text:
                text += "\n\n<blockquote>" + texts.html(source_text[:800]) + "</blockquote>"
        except (SourceUnavailableError, RuntimeError) as exc:
            text += "\n\n" + texts.SOURCE_ERROR.format(error=texts.html(str(exc)))
        await bot.send_message(chat_id, text)

    if cfg.has_contact:
        await bot.send_contact(
            chat_id,
            phone_number=cfg.contact_phone or "",
            first_name=cfg.contact_first_name or "",
            last_name=cfg.contact_last_name or None,
        )
    await bot.send_message(
        chat_id,
        texts.OTHER_TITLE.format(name=texts.html(account.name)),
        reply_markup=inline.other_menu(account, cfg),
    )


# --------------------------------------------------------------------------- .session dışa aktarma


@router.callback_query(OtherCB.filter(F.action == "export"))
async def export_session(
    callback: CallbackQuery,
    callback_data: OtherCB,
    session: AsyncSession,
    db_user: User,
    manager: UserbotManager,
    bot: Bot,
) -> None:
    account = await _load(callback, session, db_user, callback_data.aid)
    if account is None:
        return
    await callback.answer()
    try:
        path = await manager.export_session_file(account.id)
    except Exception as exc:
        await bot.send_message(
            callback.from_user.id, texts.EXPORT_FAILED.format(error=texts.html(str(exc)))
        )
        return
    try:
        await bot.send_document(
            callback.from_user.id,
            FSInputFile(path, filename=f"{account.name}.session"),
            caption=texts.EXPORT_WARNING.format(name=texts.html(account.name)),
            protect_content=True,
        )
    finally:
        shutil.rmtree(path.parent, ignore_errors=True)
