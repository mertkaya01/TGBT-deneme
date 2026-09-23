"""Uçtan uca bot akışı: gerçek Dispatcher + UserbotManager, sahte Telegram API ve sahte Telethon.

Telegram'a giden her istek ``RecordingSession`` tarafından kaydedilir; böylece kullanıcının
göreceği mesajlar ve butonlar doğrulanır.
"""

from __future__ import annotations

from aiogram.methods import AnswerCallbackQuery, DeleteMessage, EditMessageText, SendMessage
from sqlalchemy import select

from app import texts
from app.database.models import Account, ContentType
from app.keyboards.callbacks import AccountCB, NumpadCB
from tests.bot_helpers import (
    ADMIN_ID,
    STRANGER_ID,
    buttons_of,
    press,
    send_text,
    texts_of,
)


async def test_full_user_journey(env, session_maker):
    dp, bot, api, manager = env

    # --- yetkisiz kullanıcı: erişim reddi + adminlere onay bildirimi
    await send_text(dp, bot, "/start", user_id=STRANGER_ID)
    requests = api.take()
    sent_to = {int(r.chat_id) for r in requests if isinstance(r, SendMessage)}
    assert sent_to == {STRANGER_ID, ADMIN_ID}
    assert any("yetkiniz yok" in t for t in texts_of(requests))

    # --- /start: hesap yok → doğrudan oturum adı sorulur
    await send_text(dp, bot, "/start")
    assert texts_of(api.take())[-1] == texts.ASK_SESSION_NAME

    await send_text(dp, bot, "gecersiz isim!")
    assert texts_of(api.take()) == [texts.INVALID_SESSION_NAME]

    await send_text(dp, bot, "Deneme")
    assert texts_of(api.take()) == [texts.ASK_PHONE.format(name="Deneme")]

    # --- telefon → kod istenir, numpad gösterilir
    await send_text(dp, bot, "+90 555 123 45 67")
    requests = api.take()
    prompt = [r for r in requests if isinstance(r, SendMessage)][-1]
    assert "5 haneli kodu girin" in prompt.text
    assert "✅" in buttons_of(prompt)

    # --- yanlış kod: hata gösterilir, tuş takımı sıfırlanır, akış devam eder
    await send_text(dp, bot, "0 0 0 0 0")
    requests = api.take()
    assert any("Kod hatalı" in t for t in texts_of(requests))
    assert any(isinstance(r, DeleteMessage) for r in requests)  # kod mesajı silindi

    # --- kod: numpad ile 4 hane girilir, 5. hanede otomatik gönderilir
    for digit in "1234":
        await press(dp, bot, NumpadCB(key=digit).pack())
    edits = [r for r in api.take() if isinstance(r, EditMessageText)]
    assert "1 2 3 4 •" in edits[-1].text
    await press(dp, bot, NumpadCB(key="5").pack())
    requests = api.take()
    assert any(texts.LOGIN_SUCCESS.split("\n")[0] in t for t in texts_of(requests))
    panel = [r for r in requests if isinstance(r, SendMessage)][-1]
    assert panel.text.startswith("⚙️ <b>Deneme</b> hesabını yönetiyorsunuz:")
    assert buttons_of(panel) == [
        texts.BTN_AUTO_START,
        texts.BTN_AUTO_SETTINGS,
        texts.BTN_DM_ALL,
        texts.BTN_DM_REPLY_ON,
        texts.BTN_DM_SETTINGS,
        texts.BTN_FILTERS,
        texts.BTN_EXCEPTIONS,
        texts.BTN_OTHER,
        texts.BTN_HEALTH,
        texts.BTN_DELETE,
        texts.BTN_BACK_TO_LIST,
    ]

    async with session_maker() as session:
        account = await session.scalar(select(Account))
    assert account.name == "Deneme" and manager.is_connected(account.id)
    aid = account.id

    # --- mesaj ayarlanmadan başlatılamaz
    await press(dp, bot, AccountCB(action="auto", aid=aid).pack())
    answers = [r for r in api.take() if isinstance(r, AnswerCallbackQuery)]
    assert answers[-1].text == texts.AUTO_NOT_CONFIGURED

    # --- otomatik mesaj sihirbazı: metin → "0-5" → 60
    await press(dp, bot, AccountCB(action="auto_cfg", aid=aid).pack())
    assert texts.ASK_AUTO_MESSAGE in texts_of(api.take())
    await send_text(dp, bot, "MERHABA KİMLER AKTİF 😊")
    assert texts_of(api.take()) == [texts.ASK_DELAY]
    await send_text(dp, bot, "11 23")
    assert texts_of(api.take()) == [texts.ASK_CYCLE]
    await send_text(dp, bot, "0")
    assert texts_of(api.take())[0].startswith("❌")
    await send_text(dp, bot, "5")
    saved = texts_of(api.take())
    assert saved[0].startswith(texts.AUTO_SAVED)
    assert "dakikadan kısa" in saved[0]  # spam uyarısı

    async with session_maker() as session:
        cfg = (await session.get(Account, aid)).auto_config
        assert cfg.content_type == ContentType.TEXT
        assert cfg.text == "MERHABA KİMLER AKTİF 😊"
        assert (cfg.min_delay_sec, cfg.max_delay_sec, cfg.cycle_minutes) == (11, 23, 5)

    # --- başlat → worker çalışır, panel etiketi değişir
    await press(dp, bot, AccountCB(action="auto", aid=aid).pack())
    requests = api.take()
    assert [r.text for r in requests if isinstance(r, AnswerCallbackQuery)] == [
        texts.AUTO_STARTED.format(name="Deneme")
    ]
    edit = [r for r in requests if isinstance(r, EditMessageText)][-1]
    assert buttons_of(edit)[0] == texts.BTN_AUTO_STOP
    assert manager.is_worker_running(aid)

    # --- başka kullanıcı bu hesaba erişemez (beyaz listeye alınsa bile)
    await send_text(dp, bot, "/izin 99")
    api.take()
    await press(dp, bot, AccountCB(action="delete_yes", aid=aid).pack(), user_id=STRANGER_ID)
    answers = [r for r in api.take() if isinstance(r, AnswerCallbackQuery)]
    assert answers[-1].text == texts.ACCOUNT_NOT_FOUND
    assert manager.is_connected(aid)

    # --- hesabı sil
    await press(dp, bot, AccountCB(action="delete_yes", aid=aid).pack())
    api.take()
    assert not manager.is_connected(aid)
    async with session_maker() as session:
        assert await session.get(Account, aid) is None


async def test_cancel_command_clears_flow(env):
    dp, bot, api, _ = env
    await send_text(dp, bot, "/start")
    await send_text(dp, bot, "/cancel")
    requests = api.take()
    assert texts.CANCELLED in texts_of(requests)
    await send_text(dp, bot, "Deneme")  # artık oturum adı beklenmiyor
    assert texts_of(api.take()) == [texts.UNKNOWN_INPUT]
    assert not any(isinstance(r, DeleteMessage) for r in requests)
