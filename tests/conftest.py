"""Ortak test fixture'ları ve Telethon sahte nesneleri."""

from __future__ import annotations

import importlib
import os
import pkgutil
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import async_sessionmaker
from telethon import errors, functions
from telethon.tl import types as tl

import app.handlers
from app.bot_factory import create_dispatcher
from app.config import Settings
from app.database.base import Base, create_engine, create_session_maker
from app.database.models import Account, AutoMessageConfig, DMAutoReplyConfig, User
from app.userbots.userbot_manager import UserbotManager
from app.utils.crypto import SessionCipher
from app.utils.redis_lock import LockFactory
from tests.bot_helpers import RecordingSession

# --------------------------------------------------------------------------- ayarlar / DB


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        bot_token="123:TEST",
        api_id=1,
        api_hash="hash",
        session_encryption_key=Fernet.generate_key().decode(),
        # TEST_DATABASE_URL ile testler PostgreSQL üzerinde de koşturulabilir.
        database_url=os.getenv("TEST_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/test.db"),
        data_dir=tmp_path / "data",
        admin_ids=[1],
        login_attempts_per_hour=10,
    )


@pytest.fixture
def cipher(settings: Settings) -> SessionCipher:
    return SessionCipher(settings.session_encryption_key.get_secret_value())


@pytest.fixture
async def session_maker(settings: Settings) -> AsyncIterator[async_sessionmaker]:
    engine = create_engine(settings.database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield create_session_maker(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def account(session_maker, cipher) -> Account:
    async with session_maker() as session:
        session.add(User(id=10, full_name="Sahip", is_allowed=True))
        acc = Account(
            owner_id=10,
            name="DK",
            phone="+905550000000",
            tg_user_id=500,
            tg_first_name="DK",
            session_enc=cipher.encrypt("SESSION"),
            auto_message_enabled=True,
        )
        acc.auto_config = AutoMessageConfig(text="Merhaba **dünya**", entities=[])
        acc.dm_config = DMAutoReplyConfig()
        session.add(acc)
        await session.commit()
        return acc


# --------------------------------------------------------------------------- Telethon sahteleri


def group_entity(**overrides: Any) -> SimpleNamespace:
    base = {
        "left": False,
        "deactivated": False,
        "migrated_to": None,
        "creator": False,
        "admin_rights": None,
        "banned_rights": None,
        "default_banned_rights": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


@dataclass
class FakeDialog:
    id: int
    name: str
    entity: Any = field(default_factory=group_entity)
    is_group: bool = True
    is_user: bool = False
    archived: bool = False

    @property
    def input_entity(self) -> str:
        return f"peer:{self.id}"


class FakeClient:
    """Worker / sender / event handler testleri için Telethon istemcisi taklidi."""

    def __init__(self, dialogs: list[FakeDialog] | None = None) -> None:
        self.dialogs = dialogs or []
        self.calls: list[tuple[str, Any, dict]] = []
        self.failures: dict[Any, list[BaseException]] = {}
        self.uploads = 0
        self.history: dict[Any, list[Any]] = {}
        self.outgoing: dict[Any, list[Any]] = {}  # get_messages(from_user="me") sonuçları
        self.inline_queries: list[tuple[str, str]] = []
        self.inline_error: BaseException | None = None
        self.source_message = SimpleNamespace(
            id=42, message="Kaynak metin", entities=[], media=None
        )
        self.connected = True

    def fail(self, peer: Any, *excs: BaseException) -> None:
        self.failures.setdefault(peer, []).extend(excs)

    def _maybe_fail(self, peer: Any) -> None:
        queue = self.failures.get(peer)
        if queue:
            raise queue.pop(0)

    def iter_dialogs(self, archived: bool | None = None):
        async def _gen():
            for dialog in self.dialogs:
                if archived is False and dialog.archived:
                    continue
                if archived is True and not dialog.archived:
                    continue
                yield dialog

        return _gen()

    async def send_message(
        self, peer, text="", formatting_entities=None, link_preview=True, reply_to=None
    ):
        self._maybe_fail(peer)
        kwargs = {"entities": formatting_entities, "reply_to": reply_to}
        self.calls.append(("message", peer, {"text": text, **kwargs}))
        return SimpleNamespace(id=len(self.calls))

    async def send_file(self, peer, file, caption=None, formatting_entities=None):
        if isinstance(file, tl.InputMediaContact):
            self.calls.append(("contact", peer, {"phone": file.phone_number}))
            return SimpleNamespace(id=len(self.calls))
        self._maybe_fail(peer)
        self.calls.append(("file", peer, {"file": file, "caption": caption}))
        return SimpleNamespace(id=len(self.calls), photo="PHOTO_OBJ")

    async def upload_file(self, path):
        self.uploads += 1
        return tl.InputFile(id=1, parts=1, name="photo.jpg", md5_checksum="")

    async def forward_messages(self, peer, message_id, from_peer=None, drop_author=None):
        self._maybe_fail(peer)
        self.calls.append(("forward", peer, {"id": message_id, "drop_author": drop_author}))
        return [SimpleNamespace(id=len(self.calls))]

    async def get_input_entity(self, peer):
        return f"input:{peer}"

    async def get_entity(self, peer):
        raise ValueError(f"{peer} önbellekte yok")

    async def get_dialogs(self, limit=None):
        return self.dialogs

    async def get_messages(self, entity, ids=None, limit=None, max_id=None, from_user=None):
        if ids is not None:
            return self.source_message
        if from_user == "me":
            return self.outgoing.get(entity, [])
        return self.history.get(entity, [])

    async def inline_query(self, bot, query, entity=None):
        self.inline_queries.append((bot, query))
        if self.inline_error is not None:
            raise self.inline_error
        client = self

        class _Result:
            async def click(self, entity=None):
                client.calls.append(("inline", entity, {"bot": bot, "query": query}))

        return [_Result()]

    def is_connected(self) -> bool:
        return self.connected

    def add_event_handler(self, *args, **kwargs) -> None:
        pass

    def remove_event_handler(self, *args, **kwargs) -> None:
        pass

    def of_kind(self, kind: str) -> list[tuple[str, Any, dict]]:
        return [c for c in self.calls if c[0] == kind]


VALID_CODE = "12345"
PASSWORD = "gizli"


def valid_session_string(key_byte: bytes = b"\x01") -> str:
    """Telethon'un kabul ettiği gerçek biçimde bir StringSession üretir."""
    from telethon.crypto import AuthKey
    from telethon.sessions import StringSession

    source = StringSession()
    source.set_dc(2, "149.154.167.51", 443)
    source.auth_key = AuthKey(key_byte * 256)
    return source.save()


SESSION_STRING = valid_session_string(b"\x02")


class FakeSession:
    def __init__(self, value: str = SESSION_STRING) -> None:
        self.value = value

    def save(self) -> str:
        return self.value


class FakeLoginClient(FakeClient):
    """Telethon'un login API'sini taklit eder."""

    instances: list[FakeLoginClient] = []
    needs_password = False
    me_id = 777

    def __init__(self, session, api_id, api_hash, **kwargs) -> None:
        super().__init__()
        self.session = FakeSession()
        self.kwargs = kwargs
        self.authorized = False
        self.logged_out = False
        self.disconnected = False
        FakeLoginClient.instances.append(self)

    async def connect(self) -> None:
        pass

    async def disconnect(self) -> None:
        self.disconnected = True

    async def log_out(self) -> bool:
        self.logged_out = True
        return True

    async def is_user_authorized(self) -> bool:
        return True

    async def send_code_request(self, phone: str):
        if phone == "+900000000000":
            raise errors.PhoneNumberInvalidError(request=None)
        return tl.auth.SentCode(
            type=tl.auth.SentCodeTypeApp(length=5), phone_code_hash="hash-1", next_type=None
        )

    async def sign_in(self, phone=None, code=None, *, password=None, phone_code_hash=None):
        if password is not None:
            if password != PASSWORD:
                raise errors.PasswordHashInvalidError(request=None)
        else:
            assert phone_code_hash == "hash-1"
            if code != VALID_CODE:
                raise errors.PhoneCodeInvalidError(request=None)
            if self.needs_password:
                raise errors.SessionPasswordNeededError(request=None)
        self.authorized = True
        return await self.get_me()

    async def get_me(self):
        return SimpleNamespace(id=self.me_id, first_name="Test", last_name=None, username="tester")

    async def __call__(self, request):
        if isinstance(request, functions.account.GetPasswordRequest):
            return SimpleNamespace(hint="kedi")
        raise NotImplementedError(request)


@pytest.fixture
def fake_client() -> FakeClient:
    return FakeClient()


class Recorder:
    """Bildirim ve uyku çağrılarını kaydeden yardımcı."""

    def __init__(self) -> None:
        self.notifications: list[tuple[int, str]] = []
        self.sleeps: list[float] = []

    async def notify(self, user_id: int, text: str) -> None:
        self.notifications.append((user_id, text))

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)


@pytest.fixture
def recorder() -> Recorder:
    return Recorder()


@pytest.fixture
async def env(settings, session_maker, cipher, recorder):
    FakeLoginClient.instances = []
    FakeLoginClient.needs_password = False
    manager = UserbotManager(
        settings,
        session_maker,
        cipher,
        recorder.notify,
        LockFactory(None),
        client_factory=FakeLoginClient,
    )
    # Modül seviyesindeki router'lar tek bir üst router'a bağlanabilir; her testte serbest bırak.
    for module_info in pkgutil.iter_modules(app.handlers.__path__):
        module = importlib.import_module(f"app.handlers.{module_info.name}")
        if (router := getattr(module, "router", None)) is not None:
            router._parent_router = None
    session = RecordingSession()
    bot = Bot("123:TEST", session=session, default=DefaultBotProperties(parse_mode="HTML"))
    dp = create_dispatcher(settings, MemoryStorage(), session_maker, manager)
    yield dp, bot, session, manager
    await manager.shutdown()
