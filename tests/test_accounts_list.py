"""Yüzlerce hesapla kullanım: sayfalı liste, panelden doğru sayfaya dönüş, isimle arama."""

from __future__ import annotations

from aiogram.methods import EditMessageText, SendMessage
from aiogram.types import InlineKeyboardMarkup

from app import texts
from app.config import Settings
from app.database import repositories as repo
from app.database.models import User
from app.keyboards.callbacks import MenuCB
from app.keyboards.inline import ACCOUNTS_PAGE_SIZE
from tests.bot_helpers import ADMIN_ID, press, send_text

ACCOUNT_COUNT = 45


async def seed_accounts(session_maker, cipher, count: int = ACCOUNT_COUNT) -> list[int]:
    async with session_maker() as session:
        session.add(User(id=ADMIN_ID, full_name="Admin", is_admin=True, is_allowed=True))
        ids = []
        for i in range(count):
            account = await repo.create_account(
                session,
                owner_id=ADMIN_ID,
                name=f"hesap_{i:03d}",
                phone=f"+90555{i:07d}",
                tg_user_id=10_000 + i,
                tg_username=None,
                tg_first_name="x",
                session_enc=cipher.encrypt("x"),
            )
            ids.append(account.id)
        await session.commit()
        return ids


def account_buttons(markup: InlineKeyboardMarkup) -> list[str]:
    return [b.text for row in markup.inline_keyboard for b in row if "hesap_" in b.text]


def total_buttons(markup: InlineKeyboardMarkup) -> int:
    return sum(len(row) for row in markup.inline_keyboard)


def test_default_slot_limit_is_500():
    settings = Settings(
        _env_file=None,
        bot_token="1:x",
        api_id=1,
        api_hash="h",
        session_encryption_key="0" * 43 + "=",
    )
    assert settings.max_accounts_per_user == 500


async def test_account_list_is_paginated(env, session_maker, cipher):
    dp, bot, api, _ = env
    ids = await seed_accounts(session_maker, cipher)

    await press(dp, bot, MenuCB(action="accounts").pack())
    first = [r for r in api.take() if isinstance(r, EditMessageText)][-1]
    assert "(45/500)" in first.text
    assert "sayfa 1/3" in first.text
    assert "⚠️ 45 sorunlu" in first.text  # hiçbiri bağlı değil
    assert len(account_buttons(first.reply_markup)) == ACCOUNTS_PAGE_SIZE
    assert total_buttons(first.reply_markup) <= 100  # Telegram sınırı
    nav = [b.text for b in first.reply_markup.inline_keyboard[ACCOUNTS_PAGE_SIZE]]
    assert nav == ["1/3", "▶️"]

    await press(dp, bot, MenuCB(action="accounts", page=2).pack())
    last = [r for r in api.take() if isinstance(r, EditMessageText)][-1]
    assert account_buttons(last.reply_markup) == [f"🔴 hesap_{i:03d}" for i in range(40, 45)]
    nav = [b.text for b in last.reply_markup.inline_keyboard[5]]
    assert nav == ["◀️", "3/3"]

    # Panelden "Hesap Listesine Dön": hesabın bulunduğu sayfa açılır
    await press(dp, bot, MenuCB(action="accounts", aid=ids[25]).pack())
    focused = [r for r in api.take() if isinstance(r, EditMessageText)][-1]
    assert "sayfa 2/3" in focused.text
    assert "🔴 hesap_025" in account_buttons(focused.reply_markup)


async def test_open_account_by_typing_its_name(env, session_maker, cipher):
    dp, bot, api, _ = env
    await seed_accounts(session_maker, cipher, count=12)

    await send_text(dp, bot, "HESAP_007")  # tam eşleşme (büyük/küçük harf farketmez) → panel
    panel = [r for r in api.take() if isinstance(r, SendMessage)][-1]
    assert panel.text.startswith("⚙️ <b>hesap_007</b> hesabını yönetiyorsunuz:")

    await send_text(dp, bot, "hesap_01")  # kısmi eşleşme → seçim listesi
    results = [r for r in api.take() if isinstance(r, SendMessage)][-1]
    assert results.text == texts.ACCOUNT_SEARCH_RESULTS.format(query="hesap_01")
    assert account_buttons(results.reply_markup) == ["🔴 hesap_010", "🔴 hesap_011"]

    await send_text(dp, bot, "olmayan")
    assert [r.text for r in api.take() if isinstance(r, SendMessage)] == [texts.UNKNOWN_INPUT]
