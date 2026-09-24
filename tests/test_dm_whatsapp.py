"""DM oto-cevap: cevap modu, WhatsApp butonu ayarları ve bot'un inline cevabı (uçtan uca)."""

from __future__ import annotations

from aiogram.methods import AnswerCallbackQuery, AnswerInlineQuery, EditMessageText, SendMessage

from app import texts
from app.database.models import DMReplyMode
from app.keyboards.callbacks import DmCB
from app.userbots.runtime import DM_REPLY_INLINE_QUERY
from tests.bot_helpers import STRANGER_ID, login, press, send_inline_query, send_text, texts_of
from tests.conftest import FakeLoginClient

WA_URL = "https://wa.me/905551112233?text=Merhaba%2C%20bilgi%20almak%20istiyorum"


def url_buttons(request) -> list[tuple[str, str | None]]:
    markup = request.reply_markup
    return [(b.text, b.url) for row in markup.inline_keyboard for b in row] if markup else []


async def test_whatsapp_button_setup_and_inline_answer(env, session_maker):
    dp, bot, api, manager = env
    aid = await login(dp, bot, api, session_maker)
    runtime = manager.get_runtime(aid)

    # --- cevap mesajı
    await press(dp, bot, DmCB(action="set", aid=aid).pack())
    api.take()
    await send_text(dp, bot, "Merhaba! Detaylar için WhatsApp'tan yazın.")
    assert texts.DM_REPLY_SAVED in texts_of(api.take())

    # --- cevap modu: her mesaja + bekleme süresi
    await press(dp, bot, DmCB(action="mode", aid=aid).pack())
    edit = [r for r in api.take() if isinstance(r, EditMessageText)][-1]
    assert "🔁 Her mesaja (aynı kişiye en fazla 5 dk'da bir)" in edit.text
    assert runtime.dm_mode == DMReplyMode.ALWAYS
    await press(dp, bot, DmCB(action="cooldown", aid=aid).pack())
    api.take()
    assert runtime.dm_cooldown_sec == 15 * 60

    # --- WhatsApp menüsü ve ayarlar
    await press(dp, bot, DmCB(action="wa", aid=aid).pack())
    menu = [r for r in api.take() if isinstance(r, EditMessageText)][-1]
    assert texts.WA_STATUS_OFF in menu.text

    await press(dp, bot, DmCB(action="wa_phone", aid=aid).pack())
    api.take()
    await send_text(dp, bot, "+90 555 111 22 33")
    requests = api.take()
    assert texts.WA_SAVED in texts_of(requests)
    assert "via @tgbt_test_bot" in texts_of(requests)[-1]  # inline mod açık: buton aktif
    assert runtime.dm_has_button

    await press(dp, bot, DmCB(action="wa_btn", aid=aid).pack())
    api.take()
    await send_text(dp, bot, "x" * 41)
    assert texts_of(api.take())[0].startswith("❌")
    await send_text(dp, bot, "WhatsApp Destek")
    api.take()

    await press(dp, bot, DmCB(action="wa_msg", aid=aid).pack())
    api.take()
    await send_text(dp, bot, "Merhaba, bilgi almak istiyorum")
    api.take()

    # --- önizleme: bot gerçek URL butonunu gösterir
    await press(dp, bot, DmCB(action="preview", aid=aid).pack())
    preview = next(r for r in api.take() if isinstance(r, SendMessage) and r.reply_markup)
    assert preview.text == "Merhaba! Detaylar için WhatsApp'tan yazın."
    assert url_buttons(preview) == [("WhatsApp Destek", WA_URL)]

    # --- userbot'un inline sorgusu: mesaj + WhatsApp butonu döner
    await send_inline_query(dp, bot, FakeLoginClient.me_id, DM_REPLY_INLINE_QUERY)
    [answer] = [r for r in api.take() if isinstance(r, AnswerInlineQuery)]
    [result] = answer.results
    assert result.input_message_content.message_text == "Merhaba! Detaylar için WhatsApp'tan yazın."
    assert url_buttons(result) == [("WhatsApp Destek", WA_URL)]
    assert (answer.cache_time, answer.is_personal) == (0, True)

    # --- kayıtlı olmayan biri sorgularsa boş cevap; adminlere "yeni kullanıcı" bildirimi gitmez
    await send_inline_query(dp, bot, STRANGER_ID, DM_REPLY_INLINE_QUERY)
    requests = api.take()
    assert [r.results for r in requests if isinstance(r, AnswerInlineQuery)] == [[]]
    assert not any(isinstance(r, SendMessage) for r in requests)

    # --- inline mod kapalıysa kullanıcı uyarılır ve userbot link ile gönderir
    api.inline_enabled = False
    await press(dp, bot, DmCB(action="wa", aid=aid).pack())
    menu = [r for r in api.take() if isinstance(r, EditMessageText)][-1]
    assert "/setinline" in menu.text
    assert not manager.controller_bot.inline_enabled

    # --- butonu kaldır
    await press(dp, bot, DmCB(action="wa_rm", aid=aid).pack())
    assert texts.WA_REMOVED in [r.text for r in api.take() if isinstance(r, AnswerCallbackQuery)]
    assert not runtime.dm_has_button
