"""Butonlu DM oto-cevap: userbot'ların inline sorgularını cevaplar.

Telegram'da yalnızca botlar buton gönderebilir. Userbot, oto-cevap gönderirken bu bota
``@bot dm_reply`` inline sorgusu atar ve dönen sonucu sohbete bırakır; böylece mesaj
WhatsApp butonuyla birlikte ("via @bot" etiketiyle) karşı tarafa ulaşır.
"""

from __future__ import annotations

from aiogram import Router
from aiogram.types import (
    InlineQuery,
    InlineQueryResultArticle,
    InlineQueryResultCachedPhoto,
    InputTextMessageContent,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import repositories as repo
from app.keyboards import inline
from app.userbots.runtime import DM_REPLY_INLINE_QUERY
from app.utils.entities import to_aiogram_entities

router = Router(name="inline_reply")


@router.inline_query()
async def dm_reply_inline(inline_query: InlineQuery, session: AsyncSession) -> None:
    account = await repo.get_account_by_tg_id(session, inline_query.from_user.id)
    dm = account.dm_config if account is not None else None
    results = []
    if dm is not None and dm.is_configured and inline_query.query == DM_REPLY_INLINE_QUERY:
        markup = inline.whatsapp_button(dm)
        entities = to_aiogram_entities(dm.entities) or None
        if dm.photo_file_id:
            results.append(
                InlineQueryResultCachedPhoto(
                    id="dm_reply",
                    photo_file_id=dm.photo_file_id,
                    caption=dm.text or None,
                    caption_entities=entities,
                    parse_mode=None,
                    reply_markup=markup,
                )
            )
        elif dm.text.strip():
            results.append(
                InlineQueryResultArticle(
                    id="dm_reply",
                    title="Oto-cevap",
                    input_message_content=InputTextMessageContent(
                        message_text=dm.text, entities=entities, parse_mode=None
                    ),
                    reply_markup=markup,
                )
            )
    # Sonuç boşsa userbot, cevabı kendisi (link ekli) gönderir.
    await inline_query.answer(results, cache_time=0, is_personal=True)
