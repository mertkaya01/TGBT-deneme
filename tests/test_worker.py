"""Otomatik mesaj döngüsü ve gönderici testleri (sahte Telethon istemcisiyle)."""

from __future__ import annotations

import asyncio
import random
from datetime import timedelta

import pytest
from sqlalchemy import select
from telethon import errors
from telethon.tl import types as tl

from app.database.models import Account, AccountStatus, AutoMessageConfig, ContentType, utcnow
from app.userbots.errors import ErrorAction, classify
from app.userbots.runtime import AccountRuntime
from app.userbots.sender import ContactCard, MessageSender, OutgoingContent
from app.userbots.worker import AutoMessageWorker, CycleSettings, WorkerExit
from app.utils.flood import FloodGate
from app.utils.redis_lock import LocalLock
from tests.conftest import FakeClient, FakeDialog, group_entity


class StopLoop(Exception):
    """Sonsuz döngüyü testte durdurmak için."""


def make_runtime(
    client: FakeClient, account: Account, gate: FloodGate | None = None
) -> AccountRuntime:
    runtime = AccountRuntime(
        account_id=account.id,
        owner_id=account.owner_id,
        name=account.name,
        client=client,
        me_id=500,
    )
    if gate is not None:
        runtime.flood_gate = gate
    return runtime


def make_worker(runtime, session_maker, settings, recorder, **kwargs) -> AutoMessageWorker:
    return AutoMessageWorker(
        runtime,
        session_maker,
        settings,
        recorder.notify,
        LocalLock(f"test:{id(runtime)}", 60_000),
        sleep=kwargs.pop("sleep", recorder.sleep),
        rng=random.Random(1),
        **kwargs,
    )


def cycle_settings(content: OutgoingContent, **overrides) -> CycleSettings:
    values = {
        "content": content,
        "configured": True,
        "batch_size": 3,
        "min_delay_sec": 0.0,
        "max_delay_sec": 5.0,
        "cycle_minutes": 60,
        "include_archived": False,
        "last_started": None,
        "last_finished": None,
        "exception_ids": frozenset(),
    }
    values.update(overrides)
    return CycleSettings(**values)


async def load_config(session_maker, account_id: int) -> AutoMessageConfig:
    async with session_maker() as session:
        return await session.scalar(
            select(AutoMessageConfig).where(AutoMessageConfig.account_id == account_id)
        )


# --------------------------------------------------------------------------- tur mantığı


async def test_cycle_sends_in_batches_of_three(session_maker, settings, account, recorder):
    client = FakeClient([FakeDialog(-100 - i, f"Grup {i}") for i in range(7)])
    worker = make_worker(make_runtime(client, account), session_maker, settings, recorder)
    content = OutgoingContent(text="Merhaba")

    stats = await worker.run_cycle(cycle_settings(content))

    assert (stats.targets, stats.sent, stats.failed) == (7, 7, 0)
    # 3 + 3 + 1 → paketler arasında 2 bekleme, her biri 0-5 sn aralığında
    assert len(recorder.sleeps) == 2
    assert all(0 <= s <= 5 for s in recorder.sleeps)
    # formatting_entities her zaman liste: Telethon markdown ayrıştırması devreye girmez
    assert all(call[2]["entities"] == [] for call in client.of_kind("message"))

    cfg = await load_config(session_maker, account.id)
    assert (cfg.last_cycle_sent, cfg.last_cycle_targets, cfg.total_sent) == (7, 7, 7)
    assert cfg.next_cycle_at - cfg.last_cycle_finished_at == timedelta(minutes=60)


async def test_target_filtering(session_maker, settings, account, recorder):
    banned = tl.ChatBannedRights(until_date=None, send_messages=True)
    no_media = tl.ChatBannedRights(until_date=None, send_media=True)
    client = FakeClient(
        [
            FakeDialog(-1, "Normal"),
            FakeDialog(-2, "Arşiv", archived=True),
            FakeDialog(-3, "İstisna"),
            FakeDialog(-4, "Kanal", is_group=False),
            FakeDialog(-5, "Ayrıldım", entity=group_entity(left=True)),
            FakeDialog(-6, "Yazamıyorum", entity=group_entity(default_banned_rights=banned)),
            FakeDialog(
                -7, "Admin", entity=group_entity(default_banned_rights=banned, admin_rights=True)
            ),
            FakeDialog(-8, "Medyasız", entity=group_entity(default_banned_rights=no_media)),
            FakeDialog(-9, "Atıldım", entity=tl.ChatForbidden(id=9, title="x")),
        ]
    )
    runtime = make_runtime(client, account)
    worker = make_worker(runtime, session_maker, settings, recorder)
    content = OutgoingContent(text="x")

    targets = await worker.collect_targets(cycle_settings(content, exception_ids=frozenset({-3})))
    assert [t.chat_id for t in targets] == [-1, -7, -8]
    assert [t.media_allowed for t in targets] == [True, True, False]

    with_archive = await worker.collect_targets(
        cycle_settings(content, include_archived=True, exception_ids=frozenset({-3}))
    )
    assert -2 in [t.chat_id for t in with_archive]


async def test_flood_wait_pauses_whole_account_then_retries(
    session_maker, settings, account, recorder
):
    now = [0.0]
    gate_sleeps: list[float] = []

    async def gate_sleep(seconds: float) -> None:
        gate_sleeps.append(seconds)
        now[0] += seconds

    client = FakeClient([FakeDialog(-1, "A"), FakeDialog(-2, "B")])
    client.fail("peer:-1", errors.FloodWaitError(request=None, capture=30))
    runtime = make_runtime(client, account, FloodGate(clock=lambda: now[0], sleep=gate_sleep))
    worker = make_worker(runtime, session_maker, settings, recorder)

    stats = await worker.run_cycle(cycle_settings(OutgoingContent(text="x")))

    assert stats.sent == 2
    assert gate_sleeps and gate_sleeps[0] == pytest.approx(31)
    assert len(client.of_kind("message")) == 2


async def test_slow_mode_skips_chat_until_expired(session_maker, settings, account, recorder):
    client = FakeClient([FakeDialog(-1, "Yavaş"), FakeDialog(-2, "Normal")])
    client.fail("peer:-1", errors.SlowModeWaitError(request=None, capture=120))
    runtime = make_runtime(client, account)
    worker = make_worker(runtime, session_maker, settings, recorder)
    cfg = cycle_settings(OutgoingContent(text="x"))

    stats = await worker.run_cycle(cfg)
    assert (stats.sent, stats.skipped) == (1, 1)
    assert [t.chat_id for t in await worker.collect_targets(cfg)] == [-2]


async def test_media_forbidden_falls_back_to_text(
    session_maker, settings, account, recorder, tmp_path
):
    photo = tmp_path / "p.jpg"
    photo.write_bytes(b"jpg")
    no_media = tl.ChatBannedRights(until_date=None, send_media=True)
    client = FakeClient(
        [
            FakeDialog(-1, "Hata veren"),
            FakeDialog(-2, "Önceden yasaklı", entity=group_entity(default_banned_rights=no_media)),
            FakeDialog(-3, "Normal"),
            FakeDialog(-4, "Normal 2"),
        ]
    )
    client.fail("peer:-1", errors.ChatSendMediaForbiddenError(request=None))
    worker = make_worker(make_runtime(client, account), session_maker, settings, recorder)
    content = OutgoingContent(
        content_type=ContentType.PHOTO, text="Açıklama", photo_path=str(photo)
    )

    stats = await worker.run_cycle(cycle_settings(content, batch_size=1))

    assert (stats.sent, stats.fallback) == (4, 2)
    assert {c[1] for c in client.of_kind("message")} == {"peer:-1", "peer:-2"}
    assert {c[1] for c in client.of_kind("file")} == {"peer:-3", "peer:-4"}
    # Fotoğraf döngü başına bir kez yüklenir, sonra Telegram'daki kopyası kullanılır.
    assert client.uploads == 1
    assert client.of_kind("file")[-1][2]["file"] == "PHOTO_OBJ"


async def test_photo_without_caption_is_skipped_when_media_forbidden(
    session_maker, settings, account, recorder, tmp_path
):
    photo = tmp_path / "p.jpg"
    photo.write_bytes(b"jpg")
    client = FakeClient([FakeDialog(-1, "A")])
    client.fail("peer:-1", errors.ChatSendPhotosForbiddenError(request=None))
    worker = make_worker(make_runtime(client, account), session_maker, settings, recorder)
    content = OutgoingContent(content_type=ContentType.PHOTO, text="", photo_path=str(photo))

    stats = await worker.run_cycle(cycle_settings(content))
    assert (stats.sent, stats.skipped) == (0, 1)


async def test_peer_flood_stops_worker_and_marks_account(
    session_maker, settings, account, recorder
):
    client = FakeClient([FakeDialog(-1, "A")])
    client.fail("peer:-1", errors.PeerFloodError(request=None))
    runtime = make_runtime(client, account)
    worker = make_worker(runtime, session_maker, settings, recorder, skip_initial_wait=True)

    assert await worker.run() == WorkerExit.ACCOUNT_LIMITED
    async with session_maker() as session:
        acc = await session.get(Account, account.id)
        assert acc.status == AccountStatus.SPAM_LIMITED
        assert acc.auto_message_enabled is False
    assert recorder.notifications and "spam" in recorder.notifications[0][1]


async def test_session_dead_exits(session_maker, settings, account, recorder):
    client = FakeClient([FakeDialog(-1, "A")])
    client.fail("peer:-1", errors.AuthKeyUnregisteredError(request=None))
    worker = make_worker(
        make_runtime(client, account), session_maker, settings, recorder, skip_initial_wait=True
    )
    assert await worker.run() == WorkerExit.SESSION_DEAD


# --------------------------------------------------------------------------- döngü zamanlaması


async def test_restart_respects_remaining_cycle_time(session_maker, settings, account, recorder):
    async with session_maker() as session:
        cfg = await session.scalar(select(AutoMessageConfig))
        cfg.last_cycle_started_at = utcnow() - timedelta(minutes=11)
        cfg.last_cycle_finished_at = utcnow() - timedelta(minutes=10)
        await session.commit()

    sleeps: list[float] = []

    async def stop_on_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        raise StopLoop

    client = FakeClient([FakeDialog(-1, "A")])
    worker = make_worker(
        make_runtime(client, account), session_maker, settings, recorder, sleep=stop_on_sleep
    )
    with pytest.raises(StopLoop):
        await worker.run()

    assert client.calls == []  # erken tekrar gönderim yok
    assert sleeps[0] == pytest.approx(50 * 60, abs=5)
    stored = await load_config(session_maker, account.id)
    assert stored.next_cycle_at is not None


async def test_manual_start_sends_immediately_then_waits_cycle(
    session_maker, settings, account, recorder
):
    async with session_maker() as session:
        cfg = await session.scalar(select(AutoMessageConfig))
        cfg.last_cycle_finished_at = utcnow() - timedelta(minutes=1)
        cfg.cycle_minutes = 30
        await session.commit()

    sleeps: list[float] = []

    async def stop_on_long_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if seconds > 60:
            raise StopLoop

    client = FakeClient([FakeDialog(-1, "A"), FakeDialog(-2, "B")])
    worker = make_worker(
        make_runtime(client, account),
        session_maker,
        settings,
        recorder,
        sleep=stop_on_long_sleep,
        skip_initial_wait=True,
    )
    with pytest.raises(StopLoop):
        await worker.run()

    assert len(client.of_kind("message")) == 2
    assert sleeps[-1] == pytest.approx(30 * 60, abs=5)


async def test_disabled_account_stops_worker(session_maker, settings, account, recorder):
    async with session_maker() as session:
        acc = await session.get(Account, account.id)
        acc.auto_message_enabled = False
        await session.commit()
    worker = make_worker(make_runtime(FakeClient(), account), session_maker, settings, recorder)
    assert await asyncio.wait_for(worker.run(), 2) == WorkerExit.STOPPED


async def test_unconfigured_message_disables_and_notifies(
    session_maker, settings, account, recorder
):
    async with session_maker() as session:
        cfg = await session.scalar(select(AutoMessageConfig))
        cfg.text = "  "
        await session.commit()
    worker = make_worker(make_runtime(FakeClient(), account), session_maker, settings, recorder)
    assert await worker.run() == WorkerExit.NOT_CONFIGURED
    assert recorder.notifications


# --------------------------------------------------------------------------- gönderici ayrıntıları


async def test_forward_and_contact(fake_client):
    content = OutgoingContent(
        content_type=ContentType.FORWARD,
        source_peer="@kanal",
        source_msg_id=42,
        hide_forward_source=True,
        contact=ContactCard(phone="+905551112233", first_name="Ali"),
    )
    sender = MessageSender(fake_client, content)
    await sender.prepare()
    outcome = await sender.send("peer:-1")

    assert outcome.contact_sent
    forward = fake_client.of_kind("forward")[0]
    assert forward[2] == {"id": 42, "drop_author": True}
    assert fake_client.of_kind("contact")[0][2]["phone"] == "+905551112233"


async def test_forward_restricted_falls_back_to_source_text(fake_client):
    fake_client.fail("peer:-1", errors.ChatForwardsRestrictedError(request=None))
    content = OutgoingContent(
        content_type=ContentType.FORWARD, source_peer="@kanal", source_msg_id=42
    )
    sender = MessageSender(fake_client, content)
    await sender.prepare()
    outcome = await sender.send("peer:-1")
    assert outcome.fallback_used
    assert fake_client.of_kind("message")[0][2]["text"] == "Kaynak metin"


def test_error_classification():
    assert classify(errors.FloodWaitError(request=None, capture=5)) == ErrorAction.FLOOD
    assert classify(errors.SlowModeWaitError(request=None, capture=5)) == ErrorAction.SLOW_MODE
    assert classify(errors.PeerFloodError(request=None)) == ErrorAction.ACCOUNT_LIMITED
    assert classify(errors.ChatWriteForbiddenError(request=None)) == ErrorAction.SKIP_CHAT
    assert classify(errors.UserBannedInChannelError(request=None)) == ErrorAction.SKIP_CHAT
    assert (
        classify(errors.ChatSendPhotosForbiddenError(request=None)) == ErrorAction.MEDIA_FORBIDDEN
    )
    assert classify(errors.SessionRevokedError(request=None)) == ErrorAction.SESSION_DEAD
    assert classify(RuntimeError()) == ErrorAction.UNKNOWN


async def test_transient_error_before_sending_retries_after_short_backoff(
    session_maker, settings, account, recorder
):
    async with session_maker() as session:
        cfg = await session.scalar(select(AutoMessageConfig))
        cfg.last_cycle_finished_at = utcnow() - timedelta(hours=2)
        await session.commit()

    class FlakyClient(FakeClient):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.failures_left = 1

        def iter_dialogs(self, archived=None):
            if self.failures_left:
                self.failures_left -= 1
                raise ConnectionError("ağ koptu")
            return super().iter_dialogs(archived)

    sleeps: list[float] = []

    async def stop_on_long_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if seconds > 120:
            raise StopLoop

    client = FlakyClient([FakeDialog(-1, "A")])
    worker = make_worker(
        make_runtime(client, account), session_maker, settings, recorder, sleep=stop_on_long_sleep
    )
    with pytest.raises(StopLoop):
        await worker.run()

    assert sleeps[0] == 60  # kısa backoff, 60 dk'lık döngü beklemesi değil
    assert len(client.of_kind("message")) == 1  # ikinci denemede gönderildi
