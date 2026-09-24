"""DM oto-cevap ve grup kelime filtresi olay dinleyicileri."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

from telethon import errors

from app.database import repositories as repo
from app.database.models import DMReplyMode, MatchType, utcnow
from app.userbots.event_handlers import UserbotEventHandlers
from app.userbots.runtime import (
    DM_REPLY_INLINE_QUERY,
    AccountRuntime,
    CompiledFilter,
    ControllerBot,
)
from app.userbots.sender import MessageSender, OutgoingContent
from app.utils.whatsapp import append_link
from tests.conftest import FakeClient


class FakeEvent:
    def __init__(
        self, sender_id: int, chat_id: int, text: str = "", msg_id: int = 10, bot: bool = False
    ):
        self.sender_id = sender_id
        self.chat_id = chat_id
        self.id = msg_id
        self.raw_text = text
        self._sender = SimpleNamespace(id=sender_id, bot=bot, support=False, contact=False)

    async def get_sender(self):
        return self._sender

    async def get_input_chat(self):
        return f"peer:{self.chat_id}"


def make_runtime(client: FakeClient, account) -> AccountRuntime:
    runtime = AccountRuntime(
        account_id=account.id, owner_id=account.owner_id, name="DK", client=client, me_id=500
    )
    runtime.dm_auto_reply_enabled = True
    runtime.dm_sender = MessageSender(client, OutgoingContent(text="Merhaba, hoş geldiniz!"))
    return runtime


async def test_first_time_dm_gets_single_reply(session_maker, account):
    client = FakeClient()
    handlers = UserbotEventHandlers(make_runtime(client, account), session_maker)

    await handlers.on_private_message(FakeEvent(sender_id=1001, chat_id=1001))
    await handlers.on_private_message(FakeEvent(sender_id=1001, chat_id=1001, msg_id=11))

    replies = client.of_kind("message")
    assert len(replies) == 1
    assert replies[0][1] == "peer:1001"
    async with session_maker() as session:
        assert await repo.get_replied_state(session, account.id, 1001) is True


async def test_existing_contact_is_not_auto_replied(session_maker, account):
    client = FakeClient()
    client.history[1002] = [SimpleNamespace(id=5)]  # daha önce konuşulmuş
    handlers = UserbotEventHandlers(make_runtime(client, account), session_maker)

    await handlers.on_private_message(FakeEvent(sender_id=1002, chat_id=1002))

    assert client.calls == []
    async with session_maker() as session:
        assert await repo.get_replied_state(session, account.id, 1002) is False


async def test_bots_service_and_disabled_state_are_ignored(session_maker, account):
    client = FakeClient()
    runtime = make_runtime(client, account)
    handlers = UserbotEventHandlers(runtime, session_maker)

    await handlers.on_private_message(FakeEvent(sender_id=2000, chat_id=2000, bot=True))
    await handlers.on_private_message(FakeEvent(sender_id=777000, chat_id=777000))
    runtime.dm_auto_reply_enabled = False
    await handlers.on_private_message(FakeEvent(sender_id=3000, chat_id=3000))
    assert client.calls == []


async def test_group_keyword_filter_with_cooldown_and_exceptions(session_maker, account):
    client = FakeClient()
    runtime = make_runtime(client, account)
    runtime.filters = [
        CompiledFilter(
            id=1,
            keywords=("fiyat", "ücret"),
            match_type=MatchType.CONTAINS,
            reply_text="Fiyat için DM atın",
            reply_entities=(),
            cooldown_sec=60,
        )
    ]
    runtime.exception_ids = {-300}
    handlers = UserbotEventHandlers(runtime, session_maker)

    await handlers.on_group_message(
        FakeEvent(sender_id=5, chat_id=-100, text="FİYAT nedir?", msg_id=77)
    )
    await handlers.on_group_message(FakeEvent(sender_id=6, chat_id=-100, text="ücret?"))  # cooldown
    await handlers.on_group_message(FakeEvent(sender_id=7, chat_id=-200, text="alakasız mesaj"))
    await handlers.on_group_message(FakeEvent(sender_id=8, chat_id=-300, text="fiyat"))  # istisna
    await handlers.on_group_message(FakeEvent(sender_id=9, chat_id=-400, text="fiyat", bot=True))

    replies = client.of_kind("message")
    assert len(replies) == 1
    assert replies[0][1] == "peer:-100"
    assert replies[0][2]["reply_to"] == 77
    assert replies[0][2]["text"] == "Fiyat için DM atın"


# --------------------------------------------------------------------------- her mesaja cevap


def always_mode(runtime: AccountRuntime, cooldown_sec: int = 300) -> AccountRuntime:
    runtime.dm_mode = DMReplyMode.ALWAYS
    runtime.dm_cooldown_sec = cooldown_sec
    return runtime


async def test_always_mode_replies_to_known_contacts_with_cooldown(session_maker, account):
    client = FakeClient()
    client.history[1003] = [
        SimpleNamespace(id=5)
    ]  # eski tanıdık: "ilk mesaj" modunda cevap almazdı
    runtime = always_mode(make_runtime(client, account))
    handlers = UserbotEventHandlers(runtime, session_maker)

    await handlers.on_private_message(FakeEvent(sender_id=1003, chat_id=1003))
    await handlers.on_private_message(FakeEvent(sender_id=1003, chat_id=1003, msg_id=11))
    assert len(client.of_kind("message")) == 1  # bekleme süresi içinde tekrar yok

    runtime.dm_last_reply[1003] -= 301  # bekleme süresi doldu
    await handlers.on_private_message(FakeEvent(sender_id=1003, chat_id=1003, msg_id=12))
    assert len(client.of_kind("message")) == 2


async def test_always_mode_stays_quiet_while_account_is_chatting(session_maker, account):
    client = FakeClient()
    # Hesap bu kişiye 1 dk önce kendisi yazmış (elle sohbet): oto-cevap araya girmemeli.
    client.outgoing[1004] = [SimpleNamespace(id=9, date=utcnow() - timedelta(minutes=1))]
    handlers = UserbotEventHandlers(always_mode(make_runtime(client, account)), session_maker)

    await handlers.on_private_message(FakeEvent(sender_id=1004, chat_id=1004))
    assert client.calls == []

    client.outgoing[1004] = [SimpleNamespace(id=9, date=utcnow() - timedelta(hours=1))]
    handlers._rt.dm_last_reply.clear()
    await handlers.on_private_message(FakeEvent(sender_id=1004, chat_id=1004, msg_id=11))
    assert len(client.of_kind("message")) == 1


# --------------------------------------------------------------------------- WhatsApp butonu


def with_whatsapp_button(runtime: AccountRuntime, client: FakeClient) -> AccountRuntime:
    text, entities = append_link(
        "Merhaba!", [], "💬 WhatsApp'tan Yaz", "https://wa.me/905551112233"
    )
    runtime.dm_sender = MessageSender(client, OutgoingContent(text=text, entities=entities))
    runtime.dm_has_button = True
    return runtime


async def test_button_reply_is_sent_through_controller_bot(session_maker, account):
    client = FakeClient()
    runtime = with_whatsapp_button(make_runtime(client, account), client)
    bot = ControllerBot(username="tgbt_bot", inline_enabled=True)
    handlers = UserbotEventHandlers(runtime, session_maker, bot)

    await handlers.on_private_message(FakeEvent(sender_id=1005, chat_id=1005))

    assert client.inline_queries == [("tgbt_bot", DM_REPLY_INLINE_QUERY)]
    assert client.of_kind("inline") == [
        ("inline", "peer:1005", {"bot": "tgbt_bot", "query": DM_REPLY_INLINE_QUERY})
    ]
    assert client.of_kind("message") == []


async def test_inline_disabled_falls_back_to_text_link(session_maker, account):
    client = FakeClient()
    client.inline_error = errors.BotInlineDisabledError(request=None)
    runtime = with_whatsapp_button(make_runtime(client, account), client)
    bot = ControllerBot(username="tgbt_bot", inline_enabled=True)
    handlers = UserbotEventHandlers(runtime, session_maker, bot)

    await handlers.on_private_message(FakeEvent(sender_id=1006, chat_id=1006))

    [reply] = client.of_kind("message")
    assert reply[2]["text"] == "Merhaba!\n\n💬 WhatsApp'tan Yaz"
    [link] = reply[2]["entities"]
    assert link.url == "https://wa.me/905551112233"
    assert (link.offset, link.length) == (10, 19)  # emoji UTF-16'da 2 birim sayılır
    assert not bot.can_use_inline()  # bir süre tekrar denenmez
