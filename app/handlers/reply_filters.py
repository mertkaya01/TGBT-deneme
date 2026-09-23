"""🎯 Otomatik yanıt filtreleri: kelime → yanıt."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app import texts
from app.database import repositories as repo
from app.database.models import Account, MatchType, ReplyFilter, User
from app.handlers.common import answer_not_found, cleanup_state, edit_or_send, get_account
from app.keyboards import inline
from app.keyboards.callbacks import FilterCB
from app.states.states import FilterStates
from app.userbots.userbot_manager import UserbotManager
from app.utils.entities import serialize_entities
from app.utils.text import shorten, split_keywords

router = Router(name="reply_filters")

MAX_FILTERS = 50
MAX_KEYWORDS = 20
MAX_KEYWORD_LENGTH = 64
DEFAULT_COOLDOWN = 60
COOLDOWN_PRESETS = (30, 60, 120, 300, 600, 1800)
MATCH_ORDER = (MatchType.CONTAINS, MatchType.WORD, MatchType.EXACT)


async def _show_list(
    target: CallbackQuery | Message, session: AsyncSession, account: Account
) -> None:
    filters = await repo.list_filters(session, account.id)
    if filters:
        lines = []
        for i, f in enumerate(filters, 1):
            icon = "🟢" if f.is_active else "⏸"
            keywords = texts.html(shorten(", ".join(f.keywords), 50))
            lines.append(f"{i}. {icon} <b>{keywords}</b> → {texts.html(shorten(f.reply_text, 40))}")
        items = "\n".join(lines)
    else:
        items = texts.FILTERS_EMPTY
    text = texts.FILTERS_TITLE.format(
        name=texts.html(account.name), cooldown=DEFAULT_COOLDOWN, items=items
    )
    await edit_or_send(target, text, inline.filters_list(account.id, filters))


async def _show_detail(
    target: CallbackQuery | Message, aid: int, reply_filter: ReplyFilter
) -> None:
    text = texts.FILTER_DETAIL.format(
        id=reply_filter.id,
        keywords=", ".join(f"<code>{texts.html(k)}</code>" for k in reply_filter.keywords),
        match=texts.MATCH_NAMES[reply_filter.match_type],
        cooldown=reply_filter.cooldown_sec,
        state=texts.on_off(reply_filter.is_active),
        reply=texts.html(reply_filter.reply_text[:1500]),
    )
    await edit_or_send(target, text, inline.filter_detail(aid, reply_filter))


@router.callback_query(FilterCB.filter(F.action == "list"))
async def filters_list(
    callback: CallbackQuery,
    callback_data: FilterCB,
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


# --------------------------------------------------------------------------- ekleme


@router.callback_query(FilterCB.filter(F.action == "add"))
async def filter_add(
    callback: CallbackQuery,
    callback_data: FilterCB,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
) -> None:
    account = await get_account(session, db_user, callback_data.aid)
    if account is None:
        await answer_not_found(callback)
        return
    if await repo.count_filters(session, account.id) >= MAX_FILTERS:
        await callback.answer(texts.FILTER_LIMIT.format(limit=MAX_FILTERS), show_alert=True)
        return
    await state.set_state(FilterStates.keywords)
    await state.update_data(aid=account.id)
    await edit_or_send(callback, texts.ASK_FILTER_KEYWORDS, inline.cancel_flow(account.id))
    await callback.answer()


@router.message(FilterStates.keywords, F.text)
async def filter_keywords(message: Message, state: FSMContext) -> None:
    keywords = split_keywords(message.text or "")
    if (
        not keywords
        or len(keywords) > MAX_KEYWORDS
        or any(len(k) > MAX_KEYWORD_LENGTH for k in keywords)
    ):
        await message.answer(texts.INVALID_KEYWORDS)
        return
    data = await state.get_data()
    await state.update_data(keywords=keywords)
    await state.set_state(FilterStates.reply)
    await message.answer(texts.ASK_FILTER_REPLY, reply_markup=inline.cancel_flow(data["aid"]))


@router.message(FilterStates.reply, F.text)
async def filter_reply(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
    manager: UserbotManager,
) -> None:
    data = await state.get_data()
    await state.clear()
    account = await get_account(session, db_user, data["aid"])
    if account is None:
        await message.answer(texts.ACCOUNT_NOT_FOUND)
        return
    reply_filter = await repo.add_filter(
        session,
        account.id,
        keywords=data["keywords"],
        reply_text=message.text or "",
        reply_entities=serialize_entities(message.entities),
    )
    reply_filter.cooldown_sec = DEFAULT_COOLDOWN
    await session.commit()
    await manager.refresh_settings(account.id)
    await message.answer(texts.FILTER_SAVED)
    await _show_detail(message, account.id, reply_filter)


# --------------------------------------------------------------------------- detay / düzenleme


async def _load_filter(
    callback: CallbackQuery, callback_data: FilterCB, session: AsyncSession, user: User
) -> ReplyFilter | None:
    if await get_account(session, user, callback_data.aid) is None:
        await answer_not_found(callback)
        return None
    reply_filter = await repo.get_filter(session, callback_data.aid, callback_data.fid)
    if reply_filter is None:
        await callback.answer(texts.FILTER_NOT_FOUND, show_alert=True)
    return reply_filter


@router.callback_query(FilterCB.filter(F.action == "view"))
async def filter_view(
    callback: CallbackQuery, callback_data: FilterCB, session: AsyncSession, db_user: User
) -> None:
    if reply_filter := await _load_filter(callback, callback_data, session, db_user):
        await _show_detail(callback, callback_data.aid, reply_filter)
        await callback.answer()


@router.callback_query(FilterCB.filter(F.action.in_({"match", "cooldown", "toggle"})))
async def filter_update(
    callback: CallbackQuery,
    callback_data: FilterCB,
    session: AsyncSession,
    db_user: User,
    manager: UserbotManager,
) -> None:
    reply_filter = await _load_filter(callback, callback_data, session, db_user)
    if reply_filter is None:
        return
    if callback_data.action == "match":
        index = MATCH_ORDER.index(reply_filter.match_type)
        reply_filter.match_type = MATCH_ORDER[(index + 1) % len(MATCH_ORDER)]
    elif callback_data.action == "cooldown":
        later = [p for p in COOLDOWN_PRESETS if p > reply_filter.cooldown_sec]
        reply_filter.cooldown_sec = later[0] if later else COOLDOWN_PRESETS[0]
    else:
        reply_filter.is_active = not reply_filter.is_active
    await session.commit()
    await manager.refresh_settings(callback_data.aid)
    await callback.answer()
    await _show_detail(callback, callback_data.aid, reply_filter)


@router.callback_query(FilterCB.filter(F.action == "delete"))
async def filter_delete(
    callback: CallbackQuery,
    callback_data: FilterCB,
    session: AsyncSession,
    db_user: User,
    manager: UserbotManager,
) -> None:
    reply_filter = await _load_filter(callback, callback_data, session, db_user)
    if reply_filter is None:
        return
    await session.delete(reply_filter)
    await session.commit()
    await manager.refresh_settings(callback_data.aid)
    await callback.answer(texts.FILTER_DELETED)
    account = await get_account(session, db_user, callback_data.aid)
    if account is not None:
        await _show_list(callback, session, account)
