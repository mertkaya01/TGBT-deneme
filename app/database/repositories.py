"""Veritabanı erişim fonksiyonları.

Fonksiyonlar commit etmez; çağıran taraf (handler / manager) işlem sınırını belirler.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    Account,
    AccountStatus,
    AutoMessageConfig,
    DMAutoReplyConfig,
    DMRepliedUser,
    ExceptionChat,
    MatchType,
    ReplyFilter,
    User,
)

# --------------------------------------------------------------------------- kullanıcılar


async def upsert_user(
    session: AsyncSession,
    user_id: int,
    username: str | None,
    full_name: str,
    admin_ids: Sequence[int],
) -> tuple[User, bool]:
    """Kullanıcıyı getirir veya oluşturur. (kullanıcı, yeni_mi) döner."""
    user = await session.get(User, user_id)
    is_admin = user_id in admin_ids
    if user is None:
        user = User(
            id=user_id,
            username=username,
            full_name=full_name,
            is_admin=is_admin,
            is_allowed=is_admin,
        )
        session.add(user)
        return user, True
    if user.username != username:
        user.username = username
    if user.full_name != full_name:
        user.full_name = full_name
    if user.is_admin != is_admin:
        user.is_admin = is_admin
    return user, False


async def list_users(session: AsyncSession) -> Sequence[tuple[User, int]]:
    count = (
        select(func.count(Account.id))
        .where(Account.owner_id == User.id)
        .correlate(User)
        .scalar_subquery()
    )
    result = await session.execute(select(User, count).order_by(User.created_at))
    return [(row[0], row[1]) for row in result.all()]


# --------------------------------------------------------------------------- hesaplar


async def list_accounts(session: AsyncSession, owner_id: int) -> Sequence[Account]:
    result = await session.scalars(
        select(Account).where(Account.owner_id == owner_id).order_by(Account.id)
    )
    return result.all()


async def find_accounts_by_name(
    session: AsyncSession, owner_id: int, query: str, limit: int = 10
) -> Sequence[Account]:
    """Adında `query` geçen hesaplar; en kısa (en yakın) eşleşmeler önce."""
    result = await session.scalars(
        select(Account)
        .where(
            Account.owner_id == owner_id,
            func.lower(Account.name).contains(query.lower(), autoescape=True),
        )
        .order_by(func.length(Account.name), Account.id)
        .limit(limit)
    )
    return result.all()


async def count_accounts(session: AsyncSession, owner_id: int) -> int:
    return (
        await session.scalar(select(func.count(Account.id)).where(Account.owner_id == owner_id))
        or 0
    )


async def get_owned_account(
    session: AsyncSession, account_id: int, owner_id: int
) -> Account | None:
    """Hesabı yalnızca sahibine döndürür; başka kullanıcının slotuna erişimi engeller."""
    account = await session.get(Account, account_id)
    if account is None or account.owner_id != owner_id:
        return None
    return account


async def account_name_exists(session: AsyncSession, owner_id: int, name: str) -> bool:
    found = await session.scalar(
        select(Account.id).where(
            Account.owner_id == owner_id, func.lower(Account.name) == name.lower()
        )
    )
    return found is not None


async def get_account_by_tg_id(session: AsyncSession, tg_user_id: int) -> Account | None:
    return await session.scalar(select(Account).where(Account.tg_user_id == tg_user_id))


async def create_account(
    session: AsyncSession,
    *,
    owner_id: int,
    name: str,
    phone: str,
    tg_user_id: int,
    tg_username: str | None,
    tg_first_name: str,
    session_enc: str,
) -> Account:
    account = Account(
        owner_id=owner_id,
        name=name,
        phone=phone,
        tg_user_id=tg_user_id,
        tg_username=tg_username,
        tg_first_name=tg_first_name,
        session_enc=session_enc,
        status=AccountStatus.ACTIVE,
    )
    account.auto_config = AutoMessageConfig()
    account.dm_config = DMAutoReplyConfig()
    session.add(account)
    await session.flush()
    return account


async def list_accounts_by_status(
    session: AsyncSession, status: AccountStatus
) -> Sequence[Account]:
    result = await session.scalars(select(Account).where(Account.status == status))
    return result.all()


async def list_user_account_ids(session: AsyncSession, owner_id: int) -> list[int]:
    result = await session.scalars(select(Account.id).where(Account.owner_id == owner_id))
    return list(result.all())


# --------------------------------------------------------------------------- istisnalar


async def list_exception_chats(session: AsyncSession, account_id: int) -> Sequence[ExceptionChat]:
    result = await session.scalars(
        select(ExceptionChat)
        .where(ExceptionChat.account_id == account_id)
        .order_by(ExceptionChat.created_at)
    )
    return result.all()


async def exception_chat_ids(session: AsyncSession, account_id: int) -> set[int]:
    result = await session.scalars(
        select(ExceptionChat.chat_id).where(ExceptionChat.account_id == account_id)
    )
    return set(result.all())


async def add_exception_chat(
    session: AsyncSession, account_id: int, chat_id: int, title: str
) -> bool:
    exists = await session.scalar(
        select(ExceptionChat.id).where(
            ExceptionChat.account_id == account_id, ExceptionChat.chat_id == chat_id
        )
    )
    if exists:
        return False
    session.add(ExceptionChat(account_id=account_id, chat_id=chat_id, title=title[:256]))
    return True


async def remove_exception_chat(session: AsyncSession, account_id: int, chat_id: int) -> bool:
    result = await session.execute(
        delete(ExceptionChat).where(
            ExceptionChat.account_id == account_id, ExceptionChat.chat_id == chat_id
        )
    )
    return bool(result.rowcount)


# --------------------------------------------------------------------------- yanıt filtreleri


async def list_filters(session: AsyncSession, account_id: int) -> Sequence[ReplyFilter]:
    result = await session.scalars(
        select(ReplyFilter).where(ReplyFilter.account_id == account_id).order_by(ReplyFilter.id)
    )
    return result.all()


async def count_filters(session: AsyncSession, account_id: int) -> int:
    return (
        await session.scalar(
            select(func.count(ReplyFilter.id)).where(ReplyFilter.account_id == account_id)
        )
        or 0
    )


async def get_filter(session: AsyncSession, account_id: int, filter_id: int) -> ReplyFilter | None:
    reply_filter = await session.get(ReplyFilter, filter_id)
    if reply_filter is None or reply_filter.account_id != account_id:
        return None
    return reply_filter


async def add_filter(
    session: AsyncSession,
    account_id: int,
    keywords: list[str],
    reply_text: str,
    reply_entities: list[dict[str, Any]],
    match_type: MatchType = MatchType.CONTAINS,
) -> ReplyFilter:
    reply_filter = ReplyFilter(
        account_id=account_id,
        keywords=keywords,
        reply_text=reply_text,
        reply_entities=reply_entities,
        match_type=match_type,
    )
    session.add(reply_filter)
    await session.flush()
    return reply_filter


# --------------------------------------------------------------------------- DM oto-cevap


async def get_replied_state(session: AsyncSession, account_id: int, peer_id: int) -> bool | None:
    """None: hiç görülmedi, True: cevaplandı, False: eski tanıdık."""
    return await session.scalar(
        select(DMRepliedUser.replied).where(
            DMRepliedUser.account_id == account_id, DMRepliedUser.peer_id == peer_id
        )
    )


async def mark_replied(session: AsyncSession, account_id: int, peer_id: int, replied: bool) -> None:
    if await get_replied_state(session, account_id, peer_id) is None:
        session.add(DMRepliedUser(account_id=account_id, peer_id=peer_id, replied=replied))


async def count_replied(session: AsyncSession, account_id: int) -> int:
    return (
        await session.scalar(
            select(func.count(DMRepliedUser.id)).where(
                DMRepliedUser.account_id == account_id, DMRepliedUser.replied.is_(True)
            )
        )
        or 0
    )
