"""Hiçbir handler'ın yakalamadığı güncellemeler (en son eklenir)."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app import texts
from app.config import Settings
from app.database import repositories as repo
from app.database.models import User
from app.handlers.common import show_panel
from app.keyboards import inline
from app.userbots.userbot_manager import UserbotManager

router = Router(name="fallback")

MAX_QUERY_LENGTH = 32


@router.message(~StateFilter(None))
async def unexpected_in_state(message: Message) -> None:
    await message.answer("❌ Beklenen biçimde değil. Tekrar deneyin.\n\n" + texts.CANCEL_HINT)


@router.message(F.text.len() <= MAX_QUERY_LENGTH, ~F.text.startswith("/"))
async def open_account_by_name(
    message: Message,
    session: AsyncSession,
    db_user: User,
    manager: UserbotManager,
    settings: Settings,
) -> None:
    """Yüzlerce hesap arasında hızlı erişim: hesabın adını yazmak paneli açar."""
    query = (message.text or "").strip()
    matches = await repo.find_accounts_by_name(session, db_user.id, query) if query else []
    exact = next((a for a in matches if a.name.lower() == query.lower()), None)
    if exact is not None:
        await show_panel(message, exact, manager, settings)
    elif matches:
        rows = [(a, manager.is_connected(a.id)) for a in matches]
        await message.answer(
            texts.ACCOUNT_SEARCH_RESULTS.format(query=texts.html(query)),
            reply_markup=inline.account_search_results(rows),
        )
    else:
        await message.answer(texts.UNKNOWN_INPUT)


@router.message()
async def unknown_message(message: Message) -> None:
    await message.answer(texts.UNKNOWN_INPUT)


@router.callback_query()
async def stale_callback(callback: CallbackQuery) -> None:
    await callback.answer("Bu menünün süresi dolmuş. /start yazarak yeniden açın.", show_alert=True)
