"""🚫 İstisna sohbetler: gruplardan sayfalı seçim veya manuel ekleme."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app import texts
from app.database import repositories as repo
from app.database.models import Account, User
from app.handlers.common import answer_not_found, cleanup_state, edit_or_send, get_account
from app.keyboards import inline
from app.keyboards.callbacks import ExceptionCB
from app.states.states import ExceptionStates
from app.userbots.userbot_manager import UserbotManager
from app.utils.text import parse_chat_reference

router = Router(name="exceptions")


async def _show_list(
    target: CallbackQuery | Message, session: AsyncSession, account: Account
) -> None:
    chats = await repo.list_exception_chats(session, account.id)
    summary = texts.EXCEPTIONS_COUNT.format(count=len(chats)) if chats else texts.EXCEPTIONS_EMPTY
    await edit_or_send(
        target,
        texts.EXCEPTIONS_TITLE.format(name=texts.html(account.name), summary=summary),
        inline.exceptions_list(account.id, [(c.chat_id, c.title or str(c.chat_id)) for c in chats]),
    )


@router.callback_query(ExceptionCB.filter(F.action == "list"))
async def exceptions_list(
    callback: CallbackQuery,
    callback_data: ExceptionCB,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
) -> None:
    await cleanup_state(state)
    account = await get_account(session, db_user, callback_data.aid)
    if account is None:
        await answer_not_found(callback)
        return
    await _show_list(callback, session, account)
    await callback.answer()


@router.callback_query(ExceptionCB.filter(F.action == "rm"))
async def exception_remove(
    callback: CallbackQuery,
    callback_data: ExceptionCB,
    session: AsyncSession,
    db_user: User,
    manager: UserbotManager,
) -> None:
    account = await get_account(session, db_user, callback_data.aid)
    if account is None:
        await answer_not_found(callback)
        return
    await repo.remove_exception_chat(session, account.id, callback_data.cid)
    await session.commit()
    await manager.refresh_settings(account.id)
    await callback.answer(texts.EXC_REMOVED)
    await _show_list(callback, session, account)


# --------------------------------------------------------------------------- grup seçici


@router.callback_query(ExceptionCB.filter(F.action.in_({"pick", "refresh", "tog"})))
async def exception_picker(
    callback: CallbackQuery,
    callback_data: ExceptionCB,
    session: AsyncSession,
    db_user: User,
    manager: UserbotManager,
) -> None:
    account = await get_account(session, db_user, callback_data.aid)
    if account is None:
        await answer_not_found(callback)
        return
    if not manager.is_connected(account.id):
        await callback.answer(texts.NOT_CONNECTED, show_alert=True)
        return

    cached = manager.get_runtime(account.id).groups_cache  # type: ignore[union-attr]
    if cached is None or callback_data.action == "refresh":
        await edit_or_send(callback, texts.EXC_LOADING)
    groups = await manager.list_groups(account.id, force=callback_data.action == "refresh")
    if not groups:
        await callback.answer(texts.EXC_NO_GROUPS, show_alert=True)
        await _show_list(callback, session, account)
        return

    toast = None
    if callback_data.action == "tog":
        selected = await repo.exception_chat_ids(session, account.id)
        if callback_data.cid in selected:
            await repo.remove_exception_chat(session, account.id, callback_data.cid)
            toast = texts.EXC_REMOVED
        else:
            title = next((g.title for g in groups if g.chat_id == callback_data.cid), "")
            await repo.add_exception_chat(session, account.id, callback_data.cid, title)
            toast = "✅ İstisnaya eklendi."
        await session.commit()
        await manager.refresh_settings(account.id)

    selected = await repo.exception_chat_ids(session, account.id)
    pages = max(1, -(-len(groups) // inline.EXCEPTIONS_PAGE_SIZE))
    page = min(max(callback_data.page, 0), pages - 1)
    await edit_or_send(
        callback,
        texts.EXC_PICKER_TITLE.format(count=len(groups), page=page + 1, pages=pages),
        inline.exceptions_picker(account.id, groups, selected, page),
    )
    await callback.answer(toast)


# --------------------------------------------------------------------------- manuel ekleme


@router.callback_query(ExceptionCB.filter(F.action == "manual"))
async def exception_manual_prompt(
    callback: CallbackQuery,
    callback_data: ExceptionCB,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
) -> None:
    if await get_account(session, db_user, callback_data.aid) is None:
        await answer_not_found(callback)
        return
    await state.set_state(ExceptionStates.manual)
    await state.update_data(aid=callback_data.aid)
    await edit_or_send(callback, texts.ASK_EXC_MANUAL, inline.cancel_flow(callback_data.aid))
    await callback.answer()


@router.message(ExceptionStates.manual)
async def exception_manual(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    manager: UserbotManager,
) -> None:
    data = await state.get_data()
    account = await get_account(session, db_user, data["aid"])
    if account is None:
        await state.clear()
        await message.answer(texts.ACCOUNT_NOT_FOUND)
        return

    origin = message.forward_origin
    origin_chat = getattr(origin, "chat", None) or getattr(origin, "sender_chat", None)
    if origin_chat is not None:
        chat_id, title = origin_chat.id, origin_chat.title or str(origin_chat.id)
    else:
        ref = parse_chat_reference(message.text or "")
        if ref is None:
            await message.answer(texts.EXC_RESOLVE_FAILED.format(error="geçersiz biçim"))
            return
        try:
            chat_id, title = await manager.resolve_chat(account.id, ref)
        except (ValueError, RuntimeError) as exc:
            await message.answer(texts.EXC_RESOLVE_FAILED.format(error=texts.html(str(exc))))
            return

    await state.clear()
    added = await repo.add_exception_chat(session, account.id, chat_id, title)
    await session.commit()
    await manager.refresh_settings(account.id)
    await message.answer(
        texts.EXC_ADDED.format(title=texts.html(title)) if added else texts.EXC_ALREADY
    )
    await _show_list(message, session, account)
