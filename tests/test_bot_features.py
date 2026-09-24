"""Panel alt menülerinin uçtan uca testi: DM oto-cevap, filtreler, istisnalar, diğer özellikler,
sistem kontrolü ve DM toplu gönderim."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendMessage

from app import texts
from app.database import repositories as repo
from app.database.models import Account, MatchType
from app.keyboards.callbacks import AccountCB, DmCB, ExceptionCB, FilterCB, OtherCB
from tests.bot_helpers import buttons_of, login, press, send_text, texts_of
from tests.conftest import FakeDialog


def answers(requests) -> list[str | None]:
    return [r.text for r in requests if isinstance(r, AnswerCallbackQuery)]


async def test_panel_features(env, session_maker):
    dp, bot, api, manager = env
    aid = await login(dp, bot, api, session_maker)
    runtime = manager.get_runtime(aid)

    # ------------------------------------------------------------ DM oto-cevap
    await press(dp, bot, AccountCB(action="dm_toggle", aid=aid).pack())
    assert answers(api.take()) == [texts.DM_REPLY_NOT_CONFIGURED]

    await press(dp, bot, DmCB(action="set", aid=aid).pack())
    assert texts.ASK_DM_REPLY in texts_of(api.take())
    await send_text(dp, bot, "Merhaba, hoş geldin!")
    assert texts.DM_REPLY_SAVED in texts_of(api.take())

    await press(dp, bot, DmCB(action="toggle", aid=aid).pack())
    assert answers(api.take()) == [texts.DM_REPLY_ENABLED.format(name="Deneme")]
    assert runtime.dm_auto_reply_enabled and runtime.dm_sender is not None

    await press(dp, bot, DmCB(action="contacts", aid=aid).pack())
    api.take()
    assert runtime.dm_skip_contacts is True

    # ------------------------------------------------------------ yanıt filtreleri
    await press(dp, bot, FilterCB(action="add", aid=aid).pack())
    assert texts.ASK_FILTER_KEYWORDS in texts_of(api.take())
    await send_text(dp, bot, "Fiyat, ÜCRET")
    assert texts_of(api.take()) == [texts.ASK_FILTER_REPLY]
    await send_text(dp, bot, "Fiyat için DM atın")
    assert texts.FILTER_SAVED in texts_of(api.take())
    assert [f.keywords for f in runtime.filters] == [("fiyat", "ücret")]

    async with session_maker() as session:
        fid = (await repo.list_filters(session, aid))[0].id
    await press(dp, bot, FilterCB(action="match", aid=aid, fid=fid).pack())
    await press(dp, bot, FilterCB(action="cooldown", aid=aid, fid=fid).pack())
    api.take()
    assert runtime.filters[0].match_type == MatchType.WORD
    assert runtime.filters[0].cooldown_sec == 120
    await press(dp, bot, FilterCB(action="toggle", aid=aid, fid=fid).pack())
    assert runtime.filters == []
    await press(dp, bot, FilterCB(action="delete", aid=aid, fid=fid).pack())
    assert texts.FILTER_DELETED in answers(api.take())

    # ------------------------------------------------------------ istisnalar
    await press(dp, bot, ExceptionCB(action="manual", aid=aid).pack())
    api.take()
    await send_text(dp, bot, "-1001234567890")
    assert any("İstisnaya eklendi" in t for t in texts_of(api.take()))
    assert runtime.exception_ids == {-1001234567890}

    await press(dp, bot, ExceptionCB(action="rm", aid=aid, cid=-1001234567890).pack())
    api.take()
    assert runtime.exception_ids == set()

    runtime.client.dialogs = [FakeDialog(-5, "Grup A"), FakeDialog(-6, "Grup B", archived=True)]
    await press(dp, bot, ExceptionCB(action="refresh", aid=aid).pack())
    picker = [r for r in api.take() if isinstance(r, EditMessageText)][-1]
    assert "▫️ Grup A" in buttons_of(picker)
    assert "▫️ Grup B 📁" in buttons_of(picker)
    await press(dp, bot, ExceptionCB(action="tog", aid=aid, cid=-5).pack())
    picker = [r for r in api.take() if isinstance(r, EditMessageText)][-1]
    assert "✅ Grup A" in buttons_of(picker)
    assert runtime.exception_ids == {-5}

    # ------------------------------------------------------------ diğer özellikler
    await press(dp, bot, OtherCB(action="menu", aid=aid).pack())
    menu = [r for r in api.take() if isinstance(r, EditMessageText)][-1]
    assert texts.BTN_ARCHIVE.format(state=texts.STATE_OFF) in buttons_of(menu)
    await press(dp, bot, OtherCB(action="archive", aid=aid).pack())
    menu = [r for r in api.take() if isinstance(r, EditMessageText)][-1]
    assert texts.BTN_ARCHIVE.format(state=texts.STATE_ON) in buttons_of(menu)

    await press(dp, bot, OtherCB(action="contact_set", aid=aid).pack())
    api.take()
    await send_text(dp, bot, "+90 555 111 22 33 Ali Veli")
    assert any("Kişi kaydedildi" in t for t in texts_of(api.take()))

    await press(dp, bot, OtherCB(action="batch", aid=aid).pack())
    api.take()
    await send_text(dp, bot, "99")
    assert texts_of(api.take())[0].startswith("❌")
    await send_text(dp, bot, "5")
    api.take()

    await press(dp, bot, OtherCB(action="preview", aid=aid).pack())
    assert answers(api.take()) == [texts.PREVIEW_NOT_CONFIGURED]

    async with session_maker() as session:
        cfg = (await session.get(Account, aid)).auto_config
        assert cfg.include_archived and cfg.batch_size == 5
        assert (cfg.contact_phone, cfg.contact_first_name, cfg.contact_last_name) == (
            "+905551112233",
            "Ali",
            "Veli",
        )

    # ------------------------------------------------------------ sistem kontrolü
    await press(dp, bot, AccountCB(action="health", aid=aid).pack())
    report = [r for r in api.take() if isinstance(r, EditMessageText)][-1]
    assert "Sistem Kontrolu" in report.text
    assert "Test (@tester)" in report.text

    # ------------------------------------------------------------ DM toplu gönderim
    user = SimpleNamespace(id=1001, bot=False, deleted=False, is_self=False, support=False)
    bot_user = SimpleNamespace(id=1002, bot=True, deleted=False, is_self=False, support=False)
    runtime.client.dialogs = [
        FakeDialog(1001, "Ali", entity=user, is_group=False, is_user=True),
        FakeDialog(1002, "Bot", entity=bot_user, is_group=False, is_user=True),
        FakeDialog(-5, "Grup A"),
    ]
    await press(dp, bot, AccountCB(action="dm_all", aid=aid).pack())
    assert texts.ASK_BROADCAST.format(count=1) in texts_of(api.take())
    await send_text(dp, bot, "Kampanya başladı!")
    confirm = [r for r in api.take() if isinstance(r, SendMessage)][-1]
    assert confirm.text == texts.BROADCAST_CONFIRM.format(count=1)

    await press(dp, bot, DmCB(action="go", aid=aid).pack())
    for _ in range(50):
        if not runtime.broadcast_running:
            break
        await asyncio.sleep(0.01)
    final = [r for r in api.take() if isinstance(r, EditMessageText)][-1]
    assert final.text.startswith("✅ <b>DM toplu gönderim tamamlandı</b>")
    sent = runtime.client.of_kind("message")
    assert [c[1] for c in sent] == ["peer:1001"]
    assert sent[0][2]["text"] == "Kampanya başladı!"
