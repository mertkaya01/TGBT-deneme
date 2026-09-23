"""Admin komutları: beyaz liste yönetimi ve sistem özeti."""

from __future__ import annotations

import contextlib

from aiogram import Bot, Router
from aiogram.filters import Command, CommandObject, Filter
from aiogram.types import CallbackQuery, Message, TelegramObject
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import texts
from app.database import repositories as repo
from app.database.models import Account, User
from app.keyboards.callbacks import AdminCB
from app.userbots.userbot_manager import UserbotManager

router = Router(name="admin")


class IsAdmin(Filter):
    async def __call__(self, event: TelegramObject, db_user: User | None = None) -> bool:
        return bool(db_user and db_user.is_admin)


router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


def _parse_user_id(command: CommandObject) -> int | None:
    arg = (command.args or "").strip()
    return int(arg) if arg.lstrip("-").isdigit() else None


async def _set_access(
    session: AsyncSession,
    manager: UserbotManager,
    bot: Bot,
    user_id: int,
    action: str,
) -> str:
    user = await session.get(User, user_id)
    if user is None:
        return texts.ADMIN_USER_NOT_FOUND
    if user.is_admin and action != "allow":
        return texts.ADMIN_CANT_TARGET_ADMIN
    if action == "allow":
        user.is_allowed, user.is_banned = True, False
        await session.commit()
        await manager.resume_user_accounts(user_id)
        with contextlib.suppress(Exception):
            await bot.send_message(user_id, texts.USER_GRANTED)
        return texts.ADMIN_USER_ALLOWED.format(user_id=user_id)
    if action == "revoke":
        user.is_allowed = False
        await session.commit()
        await manager.stop_user_accounts(user_id)
        return texts.ADMIN_USER_REVOKED.format(user_id=user_id)
    user.is_allowed, user.is_banned = False, True
    await session.commit()
    await manager.stop_user_accounts(user_id)
    return texts.ADMIN_USER_BANNED.format(user_id=user_id)


@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    await message.answer(texts.ADMIN_USAGE)


@router.message(Command("izin", "kaldir", "yasakla"))
async def cmd_access(
    message: Message,
    command: CommandObject,
    session: AsyncSession,
    manager: UserbotManager,
    bot: Bot,
) -> None:
    user_id = _parse_user_id(command)
    if user_id is None:
        await message.answer(texts.ADMIN_BAD_ID.format(command=command.command))
        return
    action = {"izin": "allow", "kaldir": "revoke", "yasakla": "ban"}[command.command]
    await message.answer(await _set_access(session, manager, bot, user_id, action))


@router.callback_query(AdminCB.filter())
async def cb_access(
    callback: CallbackQuery,
    callback_data: AdminCB,
    session: AsyncSession,
    manager: UserbotManager,
    bot: Bot,
) -> None:
    result = await _set_access(session, manager, bot, callback_data.uid, callback_data.action)
    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.edit_text(f"{callback.message.html_text}\n\n{result}")


@router.message(Command("kullanicilar"))
async def cmd_users(message: Message, session: AsyncSession) -> None:
    rows = await repo.list_users(session)
    lines = []
    for user, account_count in rows[-100:]:
        badge = (
            "👑"
            if user.is_admin
            else ("⛔" if user.is_banned else ("✅" if user.is_allowed else "⏳"))
        )
        username = f" @{texts.html(user.username)}" if user.username else ""
        name = texts.html(user.full_name)
        lines.append(f"{badge} <code>{user.id}</code> {name}{username} — {account_count} hesap")
    await message.answer("👥 <b>Kullanıcılar</b>\n\n" + ("\n".join(lines) or "—"))


@router.message(Command("durum"))
async def cmd_status(message: Message, session: AsyncSession, manager: UserbotManager) -> None:
    users = await session.scalar(select(func.count(User.id))) or 0
    accounts = await session.scalar(select(func.count(Account.id))) or 0
    stats = manager.stats()
    await message.answer(texts.ADMIN_STATUS.format(users=users, accounts=accounts, **stats))
