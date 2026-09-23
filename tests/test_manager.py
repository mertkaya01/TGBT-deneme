"""UserbotManager: oturum açma akışı, hesap yaşam döngüsü ve ayar önbelleği."""

from __future__ import annotations

import pytest

from app.database import repositories as repo
from app.database.models import Account, MatchType, User
from app.userbots.userbot_manager import LoginError, LoginStep, UserbotManager
from app.utils.redis_lock import LockFactory
from tests.conftest import (
    PASSWORD,
    SESSION_STRING,
    VALID_CODE,
    FakeLoginClient,
    valid_session_string,
)


@pytest.fixture
def manager(settings, session_maker, cipher, recorder) -> UserbotManager:
    FakeLoginClient.instances = []
    FakeLoginClient.needs_password = False
    FakeLoginClient.me_id = 777
    return UserbotManager(
        settings,
        session_maker,
        cipher,
        recorder.notify,
        LockFactory(None),
        client_factory=FakeLoginClient,
    )


@pytest.fixture
async def owner(session_maker) -> User:
    async with session_maker() as session:
        user = User(id=42, full_name="Kullanıcı", is_allowed=True)
        session.add(user)
        await session.commit()
        return user


async def test_full_login_with_2fa(manager, owner, session_maker, cipher):
    FakeLoginClient.needs_password = True
    request = await manager.begin_login(owner.id, "+905551234567")
    assert (request.length, request.delivery) == (5, "app")
    client = FakeLoginClient.instances[-1]
    assert client.kwargs["device_model"] == "TGBT Controller"

    with pytest.raises(LoginError) as wrong_code:
        await manager.submit_code(owner.id, "00000")
    assert not wrong_code.value.fatal

    result = await manager.submit_code(owner.id, VALID_CODE)
    assert result.step == LoginStep.PASSWORD_NEEDED
    assert result.password_hint == "kedi"

    with pytest.raises(LoginError):
        await manager.submit_password(owner.id, "yanlis")
    assert (await manager.submit_password(owner.id, PASSWORD)).step == LoginStep.DONE

    account, display = await manager.complete_login(owner.id, owner.id, "Deneme")
    assert display == "Test (@tester)"
    assert manager.is_connected(account.id)
    assert not manager.has_pending_login(owner.id)

    async with session_maker() as session:
        stored = await session.get(Account, account.id)
        assert stored.tg_user_id == 777
        assert stored.session_enc != SESSION_STRING  # şifreli saklanır
        assert cipher.decrypt(stored.session_enc) == SESSION_STRING
        assert stored.auto_config is not None and stored.dm_config is not None


async def test_login_without_2fa(manager, owner):
    await manager.begin_login(owner.id, "+905551234567")
    assert (await manager.submit_code(owner.id, VALID_CODE)).step == LoginStep.DONE


async def test_invalid_phone_is_retryable(manager, owner):
    with pytest.raises(LoginError) as exc:
        await manager.begin_login(owner.id, "+900000000000")
    assert not exc.value.fatal
    assert FakeLoginClient.instances[-1].disconnected


async def test_duplicate_account_is_rejected_and_logged_out(manager, owner):
    await manager.begin_login(owner.id, "+905551234567")
    await manager.submit_code(owner.id, VALID_CODE)
    await manager.complete_login(owner.id, owner.id, "Birinci")

    await manager.begin_login(owner.id, "+905551234567")
    await manager.submit_code(owner.id, VALID_CODE)
    with pytest.raises(LoginError) as exc:
        await manager.complete_login(owner.id, owner.id, "Ikinci")
    assert exc.value.fatal
    assert FakeLoginClient.instances[-1].logged_out


async def test_login_rate_limit(manager, owner, settings):
    settings.login_attempts_per_hour = 2
    await manager.begin_login(owner.id, "+905551234567")
    await manager.begin_login(owner.id, "+905551234567")
    with pytest.raises(LoginError) as exc:
        await manager.begin_login(owner.id, "+905551234567")
    assert exc.value.fatal


async def test_cancel_and_expired_login(manager, owner, settings):
    await manager.begin_login(owner.id, "+905551234567")
    await manager.cancel_login(owner.id)
    assert FakeLoginClient.instances[-1].disconnected
    with pytest.raises(LoginError) as exc:
        await manager.submit_code(owner.id, VALID_CODE)
    assert exc.value.fatal

    settings.login_timeout_sec = 0
    await manager.begin_login(owner.id, "+905551234567")
    with pytest.raises(LoginError):
        await manager.submit_code(owner.id, VALID_CODE)


async def test_refresh_settings_builds_cache(manager, owner, session_maker):
    await manager.begin_login(owner.id, "+905551234567")
    await manager.submit_code(owner.id, VALID_CODE)
    account, _ = await manager.complete_login(owner.id, owner.id, "Deneme")

    async with session_maker() as session:
        await repo.add_filter(session, account.id, ["fiyat"], "DM atın", [], MatchType.WORD)
        paused = await repo.add_filter(session, account.id, ["kapalı"], "x", [])
        paused.is_active = False
        await repo.add_exception_chat(session, account.id, -100123, "İstisna")
        acc = await session.get(Account, account.id)
        acc.dm_config.text = "Merhaba!"
        acc.dm_auto_reply_enabled = True
        await session.commit()

    await manager.refresh_settings(account.id)
    runtime = manager.get_runtime(account.id)
    assert [f.keywords for f in runtime.filters] == [("fiyat",)]
    assert runtime.exception_ids == {-100123}
    assert runtime.dm_auto_reply_enabled and runtime.dm_sender is not None


async def _add_account(session_maker, owner, cipher, name: str, session_string: str) -> int:
    async with session_maker() as session:
        account = await repo.create_account(
            session,
            owner_id=owner.id,
            name=name,
            phone="+905550000000",
            tg_user_id=abs(hash(name)) % 10_000,
            tg_username=None,
            tg_first_name=name,
            session_enc=cipher.encrypt(session_string),
        )
        await session.commit()
        return account.id


async def test_corrupt_session_is_marked_auth_error(
    manager, owner, session_maker, cipher, recorder
):
    account_id = await _add_account(session_maker, owner, cipher, "Bozuk", "S")
    assert await manager.start_client(account_id) is None
    async with session_maker() as session:
        assert (await session.get(Account, account_id)).status == "auth_error"
    assert recorder.notifications


async def test_start_client_marks_dead_session(
    manager, owner, session_maker, cipher, recorder, monkeypatch
):
    account_id = await _add_account(session_maker, owner, cipher, "Eski", valid_session_string())

    async def unauthorized(self) -> bool:
        return False

    monkeypatch.setattr(FakeLoginClient, "is_user_authorized", unauthorized)
    assert await manager.start_client(account_id) is None

    async with session_maker() as session:
        acc = await session.get(Account, account_id)
        assert acc.status == "auth_error"
    assert recorder.notifications


async def test_auto_message_toggle_and_delete(manager, owner, session_maker, settings):
    await manager.begin_login(owner.id, "+905551234567")
    await manager.submit_code(owner.id, VALID_CODE)
    account, _ = await manager.complete_login(owner.id, owner.id, "Deneme")

    async with session_maker() as session:
        acc = await session.get(Account, account.id)
        acc.auto_config.text = "Reklam"
        await session.commit()

    await manager.set_auto_message(account.id, True)
    assert manager.is_worker_running(account.id)
    await manager.set_auto_message(account.id, False)
    assert not manager.is_worker_running(account.id)

    media_dir = settings.media_dir / str(account.id)
    media_dir.mkdir(parents=True)
    await manager.delete_account(account.id)
    assert not manager.is_connected(account.id)
    assert FakeLoginClient.instances[-1].logged_out
    assert not media_dir.exists()
    async with session_maker() as session:
        assert await session.get(Account, account.id) is None


async def test_export_session_file(manager, owner, session_maker, cipher):
    from telethon.sessions import SQLiteSession

    account_id = await _add_account(session_maker, owner, cipher, "Export", valid_session_string())

    path = await manager.export_session_file(account_id)
    assert path.suffix == ".session" and path.exists()
    restored = SQLiteSession(str(path.with_suffix("")))
    assert restored.dc_id == 2
    assert restored.auth_key.key == b"\x01" * 256
    restored.close()


async def test_ban_disables_accounts_and_allow_resumes(manager, owner, session_maker):
    await manager.begin_login(owner.id, "+905551234567")
    await manager.submit_code(owner.id, VALID_CODE)
    account, _ = await manager.complete_login(owner.id, owner.id, "Deneme")

    await manager.stop_user_accounts(owner.id)
    assert not manager.is_connected(account.id)
    await manager._reconnect_dropped()  # bakım döngüsü pasif hesabı geri açmamalı
    assert not manager.is_connected(account.id)

    await manager.resume_user_accounts(owner.id)
    assert manager.is_connected(account.id)
    async with session_maker() as session:
        assert (await session.get(Account, account.id)).status == "active"


async def test_maintenance_reconnects_accounts_that_failed_at_startup(
    manager, owner, session_maker, cipher
):
    account_id = await _add_account(session_maker, owner, cipher, "Ag", valid_session_string())
    await manager._reconnect_dropped()
    assert manager.is_connected(account_id)
