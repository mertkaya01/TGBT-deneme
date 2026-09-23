"""Userbot yöneticisi: oturum açma, istemci yaşam döngüsü, worker ve toplu gönderim görevleri."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import shutil
import tempfile
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker
from telethon import TelegramClient, errors, functions, utils
from telethon.sessions import SQLiteSession, StringSession
from telethon.tl import types as tl

from app import texts
from app.config import Settings
from app.database import repositories as repo
from app.database.models import Account, AccountStatus, ReplyFilter
from app.userbots.broadcast import BroadcastJob, ProgressCallback, collect_dm_targets
from app.userbots.errors import ErrorAction, classify
from app.userbots.event_handlers import UserbotEventHandlers
from app.userbots.runtime import AccountRuntime, CompiledFilter, GroupInfo
from app.userbots.sender import (
    MessageSender,
    OutgoingContent,
    SourceUnavailableError,
    fetch_source_message,
)
from app.userbots.worker import AutoMessageWorker, WorkerExit
from app.utils.crypto import SessionCipher, SessionDecryptError
from app.utils.entities import to_telethon_entities
from app.utils.redis_lock import LockFactory
from app.utils.text import ChatReference, format_duration

log = logging.getLogger(__name__)

Notifier = Callable[[int, str], Awaitable[None]]
ClientFactory = Callable[..., TelegramClient]

GROUPS_CACHE_TTL = 300
MAINTENANCE_INTERVAL = 60
STARTUP_CONCURRENCY = 5


# =========================================================================== login tipleri


class LoginError(Exception):
    """Kullanıcıya gösterilebilir giriş hatası.

    ``fatal=True`` ise giriş akışı sonlanır; değilse kullanıcı aynı adımı tekrar deneyebilir.
    """

    def __init__(self, message: str, *, fatal: bool = False, expired: bool = False) -> None:
        super().__init__(message)
        self.message = message
        self.fatal = fatal
        self.expired = expired


class LoginStep(StrEnum):
    PASSWORD_NEEDED = "password_needed"
    DONE = "done"


@dataclass(slots=True)
class CodeRequest:
    length: int
    delivery: str  # texts.CODE_SENT_TO anahtarı


@dataclass(slots=True)
class LoginResult:
    step: LoginStep
    password_hint: str | None = None


@dataclass(slots=True)
class PendingLogin:
    client: TelegramClient
    phone: str
    phone_code_hash: str
    created_at: float = field(default_factory=time.monotonic)
    authorized: bool = False


@dataclass(slots=True)
class HealthReport:
    connected: bool
    authorized: bool
    me: str
    ping_ms: int | None
    status: AccountStatus
    worker_running: bool
    broadcast_running: bool
    flood_remaining: float
    groups: int | None
    exceptions: int
    filters: int
    dm_auto_reply: bool
    last_error: str | None


def _describe_sent_code(sent: Any) -> CodeRequest:
    kind = getattr(sent, "type", None)
    length = getattr(kind, "length", None) or 5
    mapping: dict[type, str] = {
        tl.auth.SentCodeTypeApp: "app",
        tl.auth.SentCodeTypeSms: "sms",
        tl.auth.SentCodeTypeCall: "call",
        tl.auth.SentCodeTypeFlashCall: "flash_call",
        tl.auth.SentCodeTypeFragmentSms: "fragment",
        tl.auth.SentCodeTypeEmailCode: "email",
    }
    delivery = next((v for k, v in mapping.items() if isinstance(kind, k)), "app")
    return CodeRequest(length=int(length), delivery=delivery)


def display_name(me: Any) -> str:
    name = " ".join(filter(None, [getattr(me, "first_name", ""), getattr(me, "last_name", "")]))
    username = getattr(me, "username", None)
    return f"{name} (@{username})" if username else (name or str(getattr(me, "id", "")))


# =========================================================================== yönetici


class UserbotManager:
    def __init__(
        self,
        settings: Settings,
        session_maker: async_sessionmaker,
        cipher: SessionCipher,
        notifier: Notifier,
        lock_factory: LockFactory,
        *,
        client_factory: ClientFactory = TelegramClient,
    ) -> None:
        self._settings = settings
        self._session_maker = session_maker
        self._cipher = cipher
        self._notify = notifier
        self._lock_factory = lock_factory
        self._client_factory = client_factory

        self.runtimes: dict[int, AccountRuntime] = {}
        self._handlers: dict[int, UserbotEventHandlers] = {}
        self._account_locks: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._pending: dict[int, PendingLogin] = {}
        self._login_attempts: defaultdict[int, deque[float]] = defaultdict(deque)
        self._background: set[asyncio.Task] = set()
        self._maintenance_task: asyncio.Task | None = None
        self._closing = False

    # ------------------------------------------------------------------ genel yaşam döngüsü

    async def start(self) -> None:
        """Açılışta çağrılır: kayıtlı hesapları arka planda bağlar, bakım görevini başlatır."""
        self._spawn(self.start_all(), name="userbots:start_all")
        self._maintenance_task = asyncio.create_task(self._maintenance_loop(), name="maintenance")

    async def start_all(self) -> None:
        async with self._session_maker() as session:
            accounts = await repo.list_accounts_by_status(session, AccountStatus.ACTIVE)
            limited = await repo.list_accounts_by_status(session, AccountStatus.SPAM_LIMITED)
        semaphore = asyncio.Semaphore(STARTUP_CONCURRENCY)

        async def _start(account: Account) -> None:
            async with semaphore:
                await self.start_client(account.id)

        await asyncio.gather(*(_start(a) for a in [*accounts, *limited]), return_exceptions=True)
        log.info("%d userbot bağlandı", len(self.runtimes))

    async def shutdown(self) -> None:
        self._closing = True
        if self._maintenance_task:
            self._maintenance_task.cancel()
        for task in list(self._background):
            task.cancel()
        for user_id in list(self._pending):
            await self.cancel_login(user_id)
        await asyncio.gather(
            *(self.stop_client(aid) for aid in list(self.runtimes)), return_exceptions=True
        )

    def _spawn(self, coro: Awaitable[Any], *, name: str) -> asyncio.Task:
        task = asyncio.ensure_future(coro)
        task.set_name(name)
        self._background.add(task)
        task.add_done_callback(self._background.discard)
        return task

    def _make_client(self, session: StringSession) -> TelegramClient:
        s = self._settings
        return self._client_factory(
            session,
            s.api_id,
            s.api_hash.get_secret_value(),
            device_model=s.device_model,
            system_version=s.system_version,
            app_version=s.app_version,
            lang_code=s.lang_code,
            system_lang_code=s.lang_code,
            flood_sleep_threshold=s.flood_sleep_threshold,
            auto_reconnect=True,
            catch_up=False,
        )

    async def _maintenance_loop(self) -> None:
        """Kopan bağlantıları yeniler, yarım kalan giriş işlemlerini temizler."""
        while True:
            await asyncio.sleep(MAINTENANCE_INTERVAL)
            try:
                await self._expire_pending_logins()
                await self._reconnect_dropped()
            except Exception:
                log.exception("Bakım döngüsü hatası")

    async def _reconnect_dropped(self) -> None:
        # Açılışta ağ hatası yüzünden bağlanamamış hesapları tekrar dene.
        async with self._session_maker() as session:
            active = await repo.list_accounts_by_status(session, AccountStatus.ACTIVE)
        for account in active:
            if account.id not in self.runtimes and not self._closing:
                await self.start_client(account.id)

        for account_id, runtime in list(self.runtimes.items()):
            if runtime.client.is_connected():
                continue
            log.warning("[%s] bağlantı kopmuş, yeniden bağlanılıyor", runtime.name)
            try:
                await runtime.client.connect()
            except Exception as exc:
                log.warning("[%s] yeniden bağlanılamadı: %r", runtime.name, exc)
                continue
            if not await self._is_authorized(runtime.client):
                await self._handle_session_dead(account_id)

    @staticmethod
    async def _is_authorized(client: TelegramClient) -> bool:
        try:
            return await client.is_user_authorized()
        except errors.RPCError as exc:
            return classify(exc) != ErrorAction.SESSION_DEAD

    # ------------------------------------------------------------------ istemci yönetimi

    async def start_client(self, account_id: int) -> AccountRuntime | None:
        async with self._account_locks[account_id]:
            if account_id in self.runtimes:
                return self.runtimes[account_id]
            async with self._session_maker() as session:
                account = await session.get(Account, account_id)
                if account is None or account.status == AccountStatus.DISABLED:
                    return None
            try:
                string_session = StringSession(self._cipher.decrypt(account.session_enc))
            except (SessionDecryptError, ValueError):
                await self._mark_status(account_id, AccountStatus.AUTH_ERROR, "Oturum verisi bozuk")
                await self._notify_owner(account, texts.NOTIFY_SESSION_DEAD)
                return None

            client = self._make_client(string_session)
            try:
                await client.connect()
                if not await client.is_user_authorized():
                    raise errors.AuthKeyUnregisteredError(request=None)
                me = await client.get_me()
            except errors.RPCError as exc:
                await self._safe_disconnect(client)
                if classify(exc) == ErrorAction.SESSION_DEAD:
                    await self._mark_status(account_id, AccountStatus.AUTH_ERROR, str(exc))
                    await self._notify_owner(account, texts.NOTIFY_SESSION_DEAD)
                else:
                    log.warning("[%s] bağlanılamadı: %s", account.name, exc)
                return None
            except (OSError, ConnectionError, TimeoutError) as exc:
                await self._safe_disconnect(client)
                log.warning(
                    "[%s] ağ hatası, bakım döngüsünde tekrar denenecek: %r", account.name, exc
                )
                return None

            if account.status == AccountStatus.AUTH_ERROR:  # "Yeniden Bağlan" ile kurtarıldı
                await self._mark_status(account_id, AccountStatus.ACTIVE)
            runtime = await self._adopt(account, client, me)
            if account.auto_message_enabled:
                self._launch_worker(runtime, skip_initial_wait=False)
            return runtime

    async def _adopt(self, account: Account, client: TelegramClient, me: Any) -> AccountRuntime:
        runtime = AccountRuntime(
            account_id=account.id,
            owner_id=account.owner_id,
            name=account.name,
            client=client,
            me_id=me.id,
        )
        self.runtimes[account.id] = runtime
        await self.refresh_settings(account.id)
        handlers = UserbotEventHandlers(runtime, self._session_maker)
        handlers.register()
        self._handlers[account.id] = handlers
        log.info("[%s] userbot bağlandı: %s", account.name, display_name(me))
        return runtime

    async def stop_client(self, account_id: int, *, log_out: bool = False) -> None:
        async with self._account_locks[account_id]:
            runtime = self.runtimes.pop(account_id, None)
            if runtime is None:
                return
            await self._cancel_worker(runtime)
            if runtime.broadcast is not None:
                runtime.broadcast.cancel()
            if handlers := self._handlers.pop(account_id, None):
                handlers.unregister()
            if log_out:
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(runtime.client.log_out(), timeout=15)
            else:
                await self._persist_session(runtime)
            await self._safe_disconnect(runtime.client)

    async def reconnect(self, account_id: int) -> AccountRuntime | None:
        await self.stop_client(account_id)
        async with self._session_maker() as session:
            await session.execute(
                update(Account)
                .where(Account.id == account_id, Account.status != AccountStatus.AUTH_ERROR)
                .values(status=AccountStatus.ACTIVE)
            )
            await session.commit()
        return await self.start_client(account_id)

    async def _persist_session(self, runtime: AccountRuntime) -> None:
        """DC değişimi gibi durumlarda güncellenen oturum string'ini DB'ye yazar."""
        try:
            current = runtime.client.session.save()
            if not current:
                return
            async with self._session_maker() as session:
                account = await session.get(Account, runtime.account_id)
                if account is None:
                    return
                if self._cipher.decrypt(account.session_enc) != current:
                    account.session_enc = self._cipher.encrypt(current)
                    await session.commit()
        except Exception:
            log.debug("Oturum kaydedilemedi", exc_info=True)

    @staticmethod
    async def _safe_disconnect(client: TelegramClient) -> None:
        with contextlib.suppress(Exception):
            await client.disconnect()

    async def _handle_session_dead(self, account_id: int) -> None:
        runtime = self.runtimes.get(account_id)
        await self.stop_client(account_id)
        await self._mark_status(
            account_id, AccountStatus.AUTH_ERROR, "Oturum sonlandırıldı", disable_auto=True
        )
        async with self._session_maker() as session:
            account = await session.get(Account, account_id)
        if account is not None:
            await self._notify_owner(account, texts.NOTIFY_SESSION_DEAD)
        elif runtime is not None:
            await self._notify(
                runtime.owner_id, texts.NOTIFY_SESSION_DEAD.format(name=runtime.name)
            )

    async def _mark_status(
        self,
        account_id: int,
        status: AccountStatus,
        error: str | None = None,
        *,
        disable_auto: bool = False,
    ) -> None:
        values: dict[str, Any] = {"status": status, "last_error": error}
        if disable_auto:
            values["auto_message_enabled"] = False
        async with self._session_maker() as session:
            await session.execute(update(Account).where(Account.id == account_id).values(**values))
            await session.commit()

    async def _notify_owner(self, account: Account, template: str) -> None:
        with contextlib.suppress(Exception):
            await self._notify(account.owner_id, template.format(name=texts.html(account.name)))

    def get_runtime(self, account_id: int) -> AccountRuntime | None:
        return self.runtimes.get(account_id)

    def is_connected(self, account_id: int) -> bool:
        return account_id in self.runtimes

    # ------------------------------------------------------------------ ayar önbelleği

    async def refresh_settings(self, account_id: int) -> None:
        runtime = self.runtimes.get(account_id)
        if runtime is None:
            return
        async with self._session_maker() as session:
            account = await session.get(Account, account_id)
            if account is None:
                return
            filters: list[ReplyFilter] = list(await repo.list_filters(session, account_id))
            exception_ids = await repo.exception_chat_ids(session, account_id)
        dm = account.dm_config
        runtime.name = account.name
        runtime.dm_auto_reply_enabled = account.dm_auto_reply_enabled
        runtime.dm_skip_contacts = bool(dm and dm.skip_contacts)
        runtime.dm_sender = (
            MessageSender(runtime.client, OutgoingContent.from_dm_config(dm))
            if dm is not None and dm.is_configured
            else None
        )
        runtime.exception_ids = exception_ids
        runtime.filters = [
            CompiledFilter(
                id=f.id,
                keywords=tuple(f.keywords),
                match_type=f.match_type,
                reply_text=f.reply_text,
                reply_entities=tuple(to_telethon_entities(f.reply_entities)),
                cooldown_sec=f.cooldown_sec,
            )
            for f in filters
            if f.is_active and f.keywords
        ]

    # ------------------------------------------------------------------ otomatik mesaj worker

    def is_worker_running(self, account_id: int) -> bool:
        runtime = self.runtimes.get(account_id)
        return runtime is not None and runtime.worker_running

    async def set_auto_message(self, account_id: int, enabled: bool) -> None:
        """Otomatik mesajı açar/kapatır. Açarken ilk tur hemen başlar."""
        async with self._session_maker() as session:
            values: dict[str, Any] = {"auto_message_enabled": enabled}
            if enabled:
                values["status"] = AccountStatus.ACTIVE
                values["last_error"] = None
            await session.execute(update(Account).where(Account.id == account_id).values(**values))
            await session.commit()
        runtime = self.runtimes.get(account_id)
        if runtime is None:
            return
        await self._cancel_worker(runtime)
        if enabled:
            self._launch_worker(runtime, skip_initial_wait=True)

    async def restart_worker(self, account_id: int) -> bool:
        """Ayar değişikliğinden sonra çağrılır; döngü süresini korur (hemen tekrar göndermez)."""
        runtime = self.runtimes.get(account_id)
        if runtime is None or not runtime.worker_running:
            return False
        await self._cancel_worker(runtime)
        self._launch_worker(runtime, skip_initial_wait=False)
        return True

    def _launch_worker(self, runtime: AccountRuntime, *, skip_initial_wait: bool) -> None:
        worker = AutoMessageWorker(
            runtime,
            self._session_maker,
            self._settings,
            self._notify,
            self._lock_factory(f"worker:{runtime.account_id}"),
            skip_initial_wait=skip_initial_wait,
        )
        task = asyncio.create_task(worker.run(), name=f"worker:{runtime.account_id}")
        task.add_done_callback(lambda t, aid=runtime.account_id: self._on_worker_done(aid, t))
        runtime.worker_task = task

    def _on_worker_done(self, account_id: int, task: asyncio.Task) -> None:
        if task.cancelled() or self._closing:
            return
        if exc := task.exception():
            log.error("Worker %s çöktü, 60 sn sonra yeniden başlatılacak", account_id, exc_info=exc)
            self._spawn(self._relaunch_worker_later(account_id), name=f"relaunch:{account_id}")
            return
        if task.result() == WorkerExit.SESSION_DEAD:
            self._spawn(self._handle_session_dead(account_id), name=f"session_dead:{account_id}")

    async def _relaunch_worker_later(self, account_id: int, delay: float = 60) -> None:
        await asyncio.sleep(delay)
        runtime = self.runtimes.get(account_id)
        if runtime is None or runtime.worker_running:
            return
        async with self._session_maker() as session:
            account = await session.get(Account, account_id)
        if account is not None and account.auto_message_enabled:
            self._launch_worker(runtime, skip_initial_wait=False)

    @staticmethod
    async def _cancel_worker(runtime: AccountRuntime) -> None:
        task = runtime.worker_task
        runtime.worker_task = None
        if task is None or task.done():
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task

    # ------------------------------------------------------------------ DM

    async def set_dm_auto_reply(self, account_id: int, enabled: bool) -> None:
        async with self._session_maker() as session:
            await session.execute(
                update(Account)
                .where(Account.id == account_id)
                .values(dm_auto_reply_enabled=enabled)
            )
            await session.commit()
        await self.refresh_settings(account_id)

    async def count_dm_targets(self, account_id: int) -> int:
        runtime = self._require_runtime(account_id)
        return len(await collect_dm_targets(runtime.client))

    async def start_broadcast(
        self, account_id: int, content: OutgoingContent, on_progress: ProgressCallback
    ) -> BroadcastJob:
        runtime = self._require_runtime(account_id)
        if runtime.broadcast_running:
            raise RuntimeError(texts.BROADCAST_RUNNING)
        targets = await collect_dm_targets(runtime.client)
        job = BroadcastJob(
            runtime,
            content,
            targets,
            on_progress,
            min_delay=self._settings.dm_broadcast_min_delay,
            max_delay=self._settings.dm_broadcast_max_delay,
        )
        runtime.broadcast = job
        job.start()
        return job

    def cancel_broadcast(self, account_id: int) -> bool:
        runtime = self.runtimes.get(account_id)
        if runtime is None or not runtime.broadcast_running:
            return False
        assert runtime.broadcast is not None
        runtime.broadcast.cancel()
        return True

    def _require_runtime(self, account_id: int) -> AccountRuntime:
        runtime = self.runtimes.get(account_id)
        if runtime is None:
            raise RuntimeError(texts.NOT_CONNECTED)
        return runtime

    # ------------------------------------------------------------------ gruplar ve kaynaklar

    async def list_groups(self, account_id: int, *, force: bool = False) -> list[GroupInfo]:
        runtime = self._require_runtime(account_id)
        cached = runtime.groups_cache
        if cached and not force and time.monotonic() - cached[0] < GROUPS_CACHE_TTL:
            return cached[1]
        groups = [
            GroupInfo(chat_id=d.id, title=d.name or str(d.id), archived=d.archived)
            async for d in runtime.client.iter_dialogs()
            if d.is_group and not isinstance(d.entity, tl.ChatForbidden | tl.ChannelForbidden)
        ]
        runtime.groups_cache = (time.monotonic(), groups)
        return groups

    async def resolve_chat(self, account_id: int, ref: ChatReference) -> tuple[int, str]:
        """Elle girilen sohbeti (kimlik / kullanıcı adı / davet linki) çözer."""
        client = self._require_runtime(account_id).client
        try:
            if ref.invite_hash:
                invite = await client(functions.messages.CheckChatInviteRequest(ref.invite_hash))
                if not isinstance(invite, tl.ChatInviteAlready | tl.ChatInvitePeek):
                    raise ValueError("Userbot bu gruba üye değil.")
                entity = invite.chat
            elif ref.username:
                entity = await client.get_entity(ref.username)
            else:
                assert ref.chat_id is not None
                try:
                    entity = await client.get_entity(ref.chat_id)
                except ValueError:
                    return ref.chat_id, str(ref.chat_id)
        except (errors.RPCError, ValueError) as exc:
            raise ValueError(str(exc)) from exc
        return utils.get_peer_id(entity), utils.get_display_name(entity) or str(entity.id)

    async def verify_forward_source(self, account_id: int, peer: str, message_id: int) -> str:
        """Userbot kaynak mesaja erişebiliyor mu? Mesajın metin önizlemesini döndürür."""
        client = self._require_runtime(account_id).client
        _, message = await fetch_source_message(client, peer, message_id)
        return message.message or ""

    # ------------------------------------------------------------------ sistem kontrolü

    async def health_check(self, account_id: int) -> HealthReport:
        async with self._session_maker() as session:
            account = await session.get(Account, account_id)
            assert account is not None
            exceptions = len(await repo.exception_chat_ids(session, account_id))
            filters = [f for f in await repo.list_filters(session, account_id) if f.is_active]
        runtime = self.runtimes.get(account_id)
        report = HealthReport(
            connected=False,
            authorized=False,
            me="—",
            ping_ms=None,
            status=account.status,
            worker_running=False,
            broadcast_running=False,
            flood_remaining=0,
            groups=None,
            exceptions=exceptions,
            filters=len(filters),
            dm_auto_reply=account.dm_auto_reply_enabled,
            last_error=account.last_error,
        )
        if runtime is None:
            return report
        client = runtime.client
        report.connected = client.is_connected()
        report.worker_running = runtime.worker_running
        report.broadcast_running = runtime.broadcast_running
        report.flood_remaining = runtime.flood_gate.remaining
        try:
            started = time.perf_counter()
            me = await client.get_me()
            report.ping_ms = int((time.perf_counter() - started) * 1000)
            report.authorized = me is not None
            report.me = display_name(me) if me else "—"
            report.groups = len(await self.list_groups(account_id))
        except errors.RPCError as exc:
            if classify(exc) == ErrorAction.SESSION_DEAD:
                self._spawn(self._handle_session_dead(account_id), name="session_dead")
            report.last_error = str(exc)
        except (OSError, ConnectionError, TimeoutError) as exc:
            report.last_error = repr(exc)
        return report

    # ------------------------------------------------------------------ hesap silme / dışa aktarma

    async def delete_account(self, account_id: int) -> None:
        # Önce pasife al: bakım döngüsü silinmekte olan hesaba yeniden bağlanmasın.
        await self._mark_status(account_id, AccountStatus.DISABLED, disable_auto=True)
        await self.stop_client(account_id, log_out=True)
        async with self._session_maker() as session:
            account = await session.get(Account, account_id)
            if account is not None:
                await session.delete(account)
                await session.commit()
        shutil.rmtree(self._settings.media_dir / str(account_id), ignore_errors=True)
        self._account_locks.pop(account_id, None)

    async def export_session_file(self, account_id: int) -> Path:
        """Şifreli StringSession'dan Telethon uyumlu ``.session`` dosyası üretir."""
        async with self._session_maker() as session:
            account = await session.get(Account, account_id)
            assert account is not None
            session_string = self._cipher.decrypt(account.session_enc)
            name = account.name

        def _build() -> Path:
            source = StringSession(session_string)
            target_dir = Path(tempfile.mkdtemp(prefix="tgbt-export-"))
            base = target_dir / name
            file_session = SQLiteSession(str(base))
            file_session.set_dc(source.dc_id, source.server_address, source.port)
            file_session.auth_key = source.auth_key
            file_session.save()
            file_session.close()
            return base.with_suffix(".session")

        return await asyncio.to_thread(_build)

    # ------------------------------------------------------------------ oturum açma akışı

    def _check_login_rate(self, user_id: int) -> None:
        attempts = self._login_attempts[user_id]
        now = time.monotonic()
        while attempts and now - attempts[0] > 3600:
            attempts.popleft()
        if len(attempts) >= self._settings.login_attempts_per_hour:
            wait = 3600 - (now - attempts[0])
            raise LoginError(
                f"⏳ Çok fazla giriş denemesi. {format_duration(wait)} sonra tekrar deneyin.",
                fatal=True,
            )
        attempts.append(now)

    async def begin_login(self, user_id: int, phone: str) -> CodeRequest:
        """Yeni bir Telethon istemcisi açar ve telefona giriş kodu gönderir."""
        await self.cancel_login(user_id)
        self._check_login_rate(user_id)
        client = self._make_client(StringSession())
        try:
            await client.connect()
            sent = await client.send_code_request(phone)
        except errors.PhoneNumberInvalidError as exc:
            await self._safe_disconnect(client)
            raise LoginError("❌ Telefon numarası geçersiz. Kontrol edip tekrar girin.") from exc
        except errors.PhoneNumberBannedError as exc:
            await self._safe_disconnect(client)
            raise LoginError("🚫 Bu numara Telegram tarafından yasaklanmış.", fatal=True) from exc
        except (errors.PhoneNumberFloodError, errors.FloodWaitError) as exc:
            await self._safe_disconnect(client)
            wait = getattr(exc, "seconds", 0)
            suffix = f" {format_duration(wait)} sonra" if wait else " daha sonra"
            raise LoginError(
                f"⏳ Bu numara için çok fazla kod istendi.{suffix} tekrar deneyin.", fatal=True
            ) from exc
        except errors.ApiIdInvalidError as exc:
            await self._safe_disconnect(client)
            raise LoginError(
                "⚙️ API_ID / API_HASH geçersiz. Yöneticiyle iletişime geçin.", fatal=True
            ) from exc
        except (errors.RPCError, OSError, ConnectionError, TimeoutError) as exc:
            await self._safe_disconnect(client)
            log.warning("Kod gönderilemedi: %r", exc)
            raise LoginError(f"❌ Kod gönderilemedi: {texts.html(str(exc))}") from exc

        if isinstance(getattr(sent, "type", None), tl.auth.SentCodeTypeSetUpEmailRequired):
            await self._safe_disconnect(client)
            raise LoginError(
                "📧 Telegram bu hesap için önce e-posta doğrulaması kurulmasını istiyor. "
                "Resmi Telegram uygulamasından bir kez giriş yapıp tekrar deneyin.",
                fatal=True,
            )
        if isinstance(sent, tl.auth.SentCodeSuccess):  # nadir: zaten yetkili
            self._pending[user_id] = PendingLogin(client, phone, "", authorized=True)
            return CodeRequest(length=0, delivery="app")
        self._pending[user_id] = PendingLogin(client, phone, sent.phone_code_hash)
        return _describe_sent_code(sent)

    async def resend_code(self, user_id: int) -> CodeRequest:
        pending = self._get_pending(user_id)
        try:
            sent = await pending.client(
                functions.auth.ResendCodeRequest(pending.phone, pending.phone_code_hash)
            )
        except errors.RPCError as exc:
            raise LoginError(f"❌ Kod tekrar gönderilemedi: {texts.html(str(exc))}") from exc
        pending.phone_code_hash = sent.phone_code_hash
        pending.created_at = time.monotonic()
        return _describe_sent_code(sent)

    async def submit_code(self, user_id: int, code: str) -> LoginResult:
        pending = self._get_pending(user_id)
        try:
            await pending.client.sign_in(
                phone=pending.phone, code=code, phone_code_hash=pending.phone_code_hash
            )
        except errors.SessionPasswordNeededError:
            return LoginResult(LoginStep.PASSWORD_NEEDED, await self._password_hint(pending))
        except (errors.PhoneCodeInvalidError, errors.PhoneCodeEmptyError) as exc:
            raise LoginError("❌ Kod hatalı. Lütfen tekrar girin.") from exc
        except errors.PhoneCodeExpiredError as exc:
            raise LoginError(
                "⌛ Kodun süresi dolmuş. «Kodu Tekrar Gönder» butonunu kullanın.", expired=True
            ) from exc
        except errors.PhoneNumberUnoccupiedError as exc:
            await self.cancel_login(user_id)
            raise LoginError(
                "❌ Bu numarayla kayıtlı bir Telegram hesabı yok.", fatal=True
            ) from exc
        except errors.FloodWaitError as exc:
            raise LoginError(
                f"⏳ Çok fazla deneme. {format_duration(exc.seconds)} sonra tekrar deneyin.",
                fatal=True,
            ) from exc
        except errors.RPCError as exc:
            raise LoginError(f"❌ Giriş başarısız: {texts.html(str(exc))}") from exc
        pending.authorized = True
        return LoginResult(LoginStep.DONE)

    async def submit_password(self, user_id: int, password: str) -> LoginResult:
        pending = self._get_pending(user_id)
        try:
            await pending.client.sign_in(password=password)
        except errors.PasswordHashInvalidError as exc:
            raise LoginError("❌ 2FA şifresi hatalı. Tekrar deneyin.") from exc
        except errors.FloodWaitError as exc:
            raise LoginError(
                f"⏳ Çok fazla deneme. {format_duration(exc.seconds)} sonra tekrar deneyin.",
                fatal=True,
            ) from exc
        except errors.RPCError as exc:
            raise LoginError(f"❌ Giriş başarısız: {texts.html(str(exc))}") from exc
        pending.authorized = True
        return LoginResult(LoginStep.DONE)

    async def complete_login(self, user_id: int, owner_id: int, name: str) -> tuple[Account, str]:
        """Yetkilendirilmiş istemciyi kalıcı hesaba dönüştürür ve çalışır duruma getirir."""
        pending = self._get_pending(user_id)
        if not pending.authorized:
            raise LoginError("Giriş tamamlanmadı.")
        self._pending.pop(user_id, None)
        client = pending.client
        me = await client.get_me()
        session_string = client.session.save()

        async with self._session_maker() as session:
            if await repo.get_account_by_tg_id(session, me.id):
                await self._discard_client(client)
                raise LoginError("⚠️ Bu Telegram hesabı zaten sisteme ekli.", fatal=True)
            try:
                account = await repo.create_account(
                    session,
                    owner_id=owner_id,
                    name=name,
                    phone=pending.phone,
                    tg_user_id=me.id,
                    tg_username=me.username,
                    tg_first_name=me.first_name or "",
                    session_enc=self._cipher.encrypt(session_string),
                )
                # Kilit commit'ten önce alınır: bakım döngüsü yeni hesabı görüp aynı oturumla
                # ikinci bir bağlantı açmasın (AuthKeyDuplicated riski).
                async with self._account_locks[account.id]:
                    await session.commit()
                    await self._adopt(account, client, me)
            except IntegrityError as exc:
                await self._discard_client(client)
                raise LoginError("⚠️ Bu oturum adı veya hesap zaten kayıtlı.", fatal=True) from exc
        return account, display_name(me)

    async def _discard_client(self, client: TelegramClient) -> None:
        """Mükerrer giriş: yeni açılan oturumu Telegram tarafında da kapatır."""
        with contextlib.suppress(Exception):
            await asyncio.wait_for(client.log_out(), timeout=15)
        await self._safe_disconnect(client)

    async def cancel_login(self, user_id: int) -> None:
        pending = self._pending.pop(user_id, None)
        if pending is not None:
            await self._safe_disconnect(pending.client)

    def has_pending_login(self, user_id: int) -> bool:
        return user_id in self._pending

    def _get_pending(self, user_id: int) -> PendingLogin:
        pending = self._pending.get(user_id)
        if pending is None:
            raise LoginError(texts.LOGIN_EXPIRED, fatal=True)
        if time.monotonic() - pending.created_at > self._settings.login_timeout_sec:
            self._spawn(self.cancel_login(user_id), name="login:expire")
            raise LoginError(texts.LOGIN_EXPIRED, fatal=True)
        return pending

    @staticmethod
    async def _password_hint(pending: PendingLogin) -> str | None:
        with contextlib.suppress(Exception):
            password = await pending.client(functions.account.GetPasswordRequest())
            return password.hint or None
        return None

    async def _expire_pending_logins(self) -> None:
        now = time.monotonic()
        expired = [
            uid
            for uid, p in self._pending.items()
            if now - p.created_at > self._settings.login_timeout_sec
        ]
        for user_id in expired:
            await self.cancel_login(user_id)

    # ------------------------------------------------------------------ admin

    async def stop_user_accounts(self, owner_id: int) -> None:
        async with self._session_maker() as session:
            account_ids = await repo.list_user_account_ids(session, owner_id)
            await session.execute(
                update(Account)
                .where(Account.owner_id == owner_id, Account.status != AccountStatus.AUTH_ERROR)
                .values(
                    status=AccountStatus.DISABLED,
                    auto_message_enabled=False,
                    dm_auto_reply_enabled=False,
                )
            )
            await session.commit()
        for account_id in account_ids:
            await self.stop_client(account_id)

    async def resume_user_accounts(self, owner_id: int) -> None:
        """Erişimi yeniden açılan kullanıcının hesaplarını bağlar (döngüler kapalı başlar)."""
        async with self._session_maker() as session:
            account_ids = await repo.list_user_account_ids(session, owner_id)
            await session.execute(
                update(Account)
                .where(Account.owner_id == owner_id, Account.status == AccountStatus.DISABLED)
                .values(status=AccountStatus.ACTIVE)
            )
            await session.commit()
        for account_id in account_ids:
            await self.start_client(account_id)

    def stats(self) -> dict[str, int]:
        return {
            "connected": len(self.runtimes),
            "workers": sum(r.worker_running for r in self.runtimes.values()),
            "broadcasts": sum(r.broadcast_running for r in self.runtimes.values()),
        }


__all__ = [
    "CodeRequest",
    "HealthReport",
    "LoginError",
    "LoginResult",
    "LoginStep",
    "SourceUnavailableError",
    "UserbotManager",
]
