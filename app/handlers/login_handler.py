"""Oturum açma akışı (FSM): oturum adı → telefon → kod → (2FA) → hesap paneli.

Kod iki yolla girilebilir:
* Yazarak: "1 8 7 3 5" veya "18-735". Mesaj okunur okunmaz silinir.
* Inline tuş takımıyla: kod hiç mesaj olarak gönderilmez. Telegram, giriş kodunun bir sohbette
  paylaşıldığını algılarsa kodu iptal edebildiği için en güvenli yöntem budur.
"""

from __future__ import annotations

import contextlib
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove
from sqlalchemy.ext.asyncio import AsyncSession

from app import texts
from app.config import Settings
from app.database import repositories as repo
from app.database.models import User
from app.handlers.common import (
    delete_quietly,
    edit_or_send,
    get_account,
    show_accounts,
    show_panel,
    slot_limit,
)
from app.keyboards import inline
from app.keyboards.callbacks import LoginCB, NumpadCB
from app.states.states import LoginStates
from app.userbots.userbot_manager import CodeRequest, LoginError, LoginStep, UserbotManager
from app.utils.text import extract_code, is_valid_session_name, normalize_phone

log = logging.getLogger(__name__)
router = Router(name="login")


async def ask_session_name(target: Message | CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(LoginStates.name)
    await edit_or_send(target, texts.ASK_SESSION_NAME, inline.login_cancel())


def _code_prompt(data: dict) -> str:
    length = data.get("code_len") or 5
    buffer = data.get("code_buf", "")
    display = " ".join(list(buffer) + ["•"] * max(length - len(buffer), 0))
    where = texts.CODE_SENT_TO.get(data.get("delivery", "app"), texts.CODE_SENT_TO["app"])
    return texts.ASK_CODE.format(length=length, where=where) + texts.CODE_DISPLAY.format(
        display=display
    )


async def _refresh_code_prompt(bot: Bot, chat_id: int, state: FSMContext) -> None:
    data = await state.get_data()
    prompt_id = data.get("prompt_id")
    if not prompt_id:
        return
    with contextlib.suppress(TelegramBadRequest):
        await bot.edit_message_text(
            _code_prompt(data), chat_id=chat_id, message_id=prompt_id, reply_markup=inline.numpad()
        )


# --------------------------------------------------------------------------- 1) oturum adı


@router.message(LoginStates.name, F.text)
async def on_session_name(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    settings: Settings,
) -> None:
    name = (message.text or "").strip()
    if not is_valid_session_name(name):
        await message.answer(texts.INVALID_SESSION_NAME)
        return
    limit = slot_limit(db_user, settings)
    if await repo.count_accounts(session, db_user.id) >= limit:
        await state.clear()
        await message.answer(texts.SLOT_LIMIT_REACHED.format(limit=limit))
        return
    if await repo.account_name_exists(session, db_user.id, name):
        await message.answer(texts.SESSION_NAME_TAKEN)
        return
    await state.update_data(name=name)
    await state.set_state(LoginStates.phone)
    await message.answer(
        texts.ASK_PHONE.format(name=texts.html(name)), reply_markup=inline.share_phone_keyboard()
    )


# --------------------------------------------------------------------------- 2) telefon


@router.message(LoginStates.phone, F.text | F.contact)
async def on_phone(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    manager: UserbotManager,
    settings: Settings,
) -> None:
    if message.contact:
        raw = message.contact.phone_number
        raw = raw if raw.startswith("+") else "+" + raw
    else:
        raw = message.text or ""
    phone = normalize_phone(raw)
    if phone is None:
        await message.answer(texts.INVALID_PHONE)
        return

    status = await message.answer(texts.SENDING_CODE, reply_markup=ReplyKeyboardRemove())
    try:
        request = await manager.begin_login(db_user.id, phone)
    except LoginError as exc:
        await status.edit_text(exc.message)
        if exc.fatal:
            await state.clear()
        return

    await state.update_data(phone=phone)
    if request.length == 0:  # Telegram kodu atlayıp doğrudan yetkilendirdi
        await _finish_login(status, state, session, db_user, manager, settings)
        return
    await _store_code_request(state, request)
    await state.set_state(LoginStates.code)
    await delete_quietly(status)
    prompt = await message.answer(
        _code_prompt(await state.get_data()), reply_markup=inline.numpad()
    )
    await state.update_data(prompt_id=prompt.message_id)


async def _store_code_request(state: FSMContext, request: CodeRequest) -> None:
    await state.update_data(code_len=request.length, delivery=request.delivery, code_buf="")


# --------------------------------------------------------------------------- 3) kod


@router.message(LoginStates.code, F.text)
async def on_code_text(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    manager: UserbotManager,
    settings: Settings,
) -> None:
    await delete_quietly(message)  # kod sohbette kalmasın
    data = await state.get_data()
    length = data.get("code_len") or 5
    code = extract_code(message.text or "", length)
    if code is None:
        await message.answer(texts.INVALID_CODE_FORMAT.format(length=length))
        return
    await _submit_code(message, state, session, db_user, manager, settings, code)


@router.callback_query(LoginStates.code, NumpadCB.filter())
async def on_numpad(
    callback: CallbackQuery,
    callback_data: NumpadCB,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    manager: UserbotManager,
    settings: Settings,
    bot: Bot,
) -> None:
    data = await state.get_data()
    length = data.get("code_len") or 5
    buffer: str = data.get("code_buf", "")
    key = callback_data.key

    if key == "del":
        buffer = buffer[:-1]
    elif key == "ok":
        if len(buffer) != length:
            await callback.answer(texts.CODE_INCOMPLETE.format(length=length), show_alert=True)
            return
    elif key.isdigit() and len(buffer) < length:
        buffer += key
    await state.update_data(code_buf=buffer)
    await callback.answer()

    if len(buffer) == length and key != "del":
        assert isinstance(callback.message, Message)
        await _submit_code(callback.message, state, session, db_user, manager, settings, buffer)
    else:
        await _refresh_code_prompt(bot, callback.from_user.id, state)


async def _submit_code(
    anchor: Message,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    manager: UserbotManager,
    settings: Settings,
    code: str,
) -> None:
    status = await anchor.answer(texts.CHECKING_CODE)
    try:
        result = await manager.submit_code(db_user.id, code)
    except LoginError as exc:
        await status.edit_text(exc.message)
        if exc.fatal:
            await state.clear()
            return
        await state.update_data(code_buf="")
        await _refresh_code_prompt(anchor.bot, anchor.chat.id, state)  # type: ignore[arg-type]
        return

    if result.step == LoginStep.PASSWORD_NEEDED:
        await state.set_state(LoginStates.password)
        hint = (
            f" (ipucu: <i>{texts.html(result.password_hint)}</i>)" if result.password_hint else ""
        )
        await status.edit_text(
            texts.ASK_PASSWORD.format(hint=hint), reply_markup=inline.login_cancel()
        )
        return
    await _finish_login(status, state, session, db_user, manager, settings)


@router.callback_query(LoginStates.code, LoginCB.filter(F.action == "resend"))
async def on_resend(
    callback: CallbackQuery,
    state: FSMContext,
    db_user: User,
    manager: UserbotManager,
    bot: Bot,
) -> None:
    try:
        request = await manager.resend_code(db_user.id)
    except LoginError as exc:
        await callback.answer(exc.message, show_alert=True)
        if exc.fatal:
            await state.clear()
        return
    await _store_code_request(state, request)
    await callback.answer(texts.CODE_RESENT)
    await _refresh_code_prompt(bot, callback.from_user.id, state)


# --------------------------------------------------------------------------- 4) 2FA


@router.message(LoginStates.password, F.text)
async def on_password(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    manager: UserbotManager,
    settings: Settings,
) -> None:
    password = message.text or ""
    await delete_quietly(message)  # şifre sohbette kalmasın
    status = await message.answer(texts.CHECKING_PASSWORD)
    try:
        await manager.submit_password(db_user.id, password)
    except LoginError as exc:
        await status.edit_text(exc.message)
        if exc.fatal:
            await state.clear()
        return
    await _finish_login(status, state, session, db_user, manager, settings)


# --------------------------------------------------------------------------- tamamlama / iptal


async def _finish_login(
    status: Message,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    manager: UserbotManager,
    settings: Settings,
) -> None:
    data = await state.get_data()
    await state.clear()
    try:
        account, display = await manager.complete_login(db_user.id, db_user.id, data["name"])
    except LoginError as exc:
        await status.edit_text(exc.message)
        return
    await status.edit_text(
        texts.LOGIN_SUCCESS.format(
            name=texts.html(account.name),
            display=texts.html(display),
            phone=texts.html(account.phone),
        )
    )
    fresh = await get_account(session, db_user, account.id)
    if fresh is not None:
        await show_panel(status, fresh, manager, settings)


@router.callback_query(LoginCB.filter(F.action == "cancel"))
async def on_login_cancel(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    manager: UserbotManager,
    settings: Settings,
) -> None:
    await manager.cancel_login(db_user.id)
    await state.clear()
    await callback.answer(texts.CANCELLED)
    await show_accounts(callback, session, db_user, manager, settings)
