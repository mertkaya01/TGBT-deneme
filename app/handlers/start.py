"""/start, hesap listesi, bilgi ekranı ve /cancel."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove
from sqlalchemy.ext.asyncio import AsyncSession

from app import texts
from app.config import Settings
from app.database import repositories as repo
from app.database.models import User
from app.handlers.common import (
    cleanup_state,
    edit_or_send,
    get_account,
    show_accounts,
    show_panel,
    slot_limit,
)
from app.handlers.login_handler import ask_session_name
from app.keyboards import inline
from app.keyboards.callbacks import FlowCB, MenuCB
from app.userbots.userbot_manager import UserbotManager

router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    manager: UserbotManager,
    settings: Settings,
) -> None:
    await cleanup_state(state)
    await manager.cancel_login(db_user.id)
    if await repo.count_accounts(session, db_user.id) == 0:
        await message.answer(texts.WELCOME_NEW, reply_markup=ReplyKeyboardRemove())
        await ask_session_name(message, state)
        return
    await show_accounts(message, session, db_user, manager, settings)


@router.message(Command("menu"))
async def cmd_menu(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    manager: UserbotManager,
    settings: Settings,
) -> None:
    await cleanup_state(state)
    await show_accounts(message, session, db_user, manager, settings)


@router.message(Command("cancel", "iptal"))
async def cmd_cancel(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    manager: UserbotManager,
    settings: Settings,
) -> None:
    if await state.get_state() is None:
        await message.answer(texts.NOTHING_TO_CANCEL, reply_markup=ReplyKeyboardRemove())
        return
    data = await cleanup_state(state)
    await manager.cancel_login(db_user.id)
    await message.answer(texts.CANCELLED, reply_markup=ReplyKeyboardRemove())
    account = await get_account(session, db_user, data["aid"]) if data.get("aid") else None
    if account is not None:
        await show_panel(message, account, manager, settings)
    else:
        await show_accounts(message, session, db_user, manager, settings)


@router.callback_query(FlowCB.filter())
async def flow_cancel(
    callback: CallbackQuery,
    callback_data: FlowCB,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    manager: UserbotManager,
    settings: Settings,
) -> None:
    await cleanup_state(state)
    await callback.answer(texts.CANCELLED)
    account = await get_account(session, db_user, callback_data.aid)
    if account is None:
        await show_accounts(callback, session, db_user, manager, settings)
        return
    await show_panel(callback, account, manager, settings)


@router.message(Command("help", "yardim"))
async def cmd_help(message: Message) -> None:
    await message.answer(texts.INFO, reply_markup=inline.info_back())


@router.callback_query(MenuCB.filter(F.action == "accounts"))
async def cb_accounts(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    manager: UserbotManager,
    settings: Settings,
) -> None:
    await cleanup_state(state)
    await show_accounts(callback, session, db_user, manager, settings)
    await callback.answer()


@router.callback_query(MenuCB.filter(F.action == "add"))
async def cb_add_account(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    settings: Settings,
) -> None:
    limit = slot_limit(db_user, settings)
    if await repo.count_accounts(session, db_user.id) >= limit:
        await callback.answer(texts.SLOT_LIMIT_REACHED.format(limit=limit), show_alert=True)
        return
    await ask_session_name(callback, state)
    await callback.answer()


@router.callback_query(MenuCB.filter(F.action == "info"))
async def cb_info(callback: CallbackQuery) -> None:
    await edit_or_send(callback, texts.INFO, inline.info_back())
    await callback.answer()
