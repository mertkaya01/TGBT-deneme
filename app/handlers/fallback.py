"""Hiçbir handler'ın yakalamadığı güncellemeler (en son eklenir)."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import StateFilter
from aiogram.types import CallbackQuery, Message

from app import texts

router = Router(name="fallback")


@router.message(~StateFilter(None))
async def unexpected_in_state(message: Message) -> None:
    await message.answer("❌ Beklenen biçimde değil. Tekrar deneyin.\n\n" + texts.CANCEL_HINT)


@router.message()
async def unknown_message(message: Message) -> None:
    await message.answer(texts.UNKNOWN_INPUT)


@router.callback_query()
async def stale_callback(callback: CallbackQuery) -> None:
    await callback.answer("Bu menünün süresi dolmuş. /start yazarak yeniden açın.", show_alert=True)
