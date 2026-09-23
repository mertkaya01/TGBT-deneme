"""Inline klavyeler."""

from __future__ import annotations

from collections.abc import Sequence

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app import texts
from app.database.models import (
    Account,
    AccountStatus,
    AutoMessageConfig,
    DMAutoReplyConfig,
    ReplyFilter,
)
from app.keyboards.callbacks import (
    AccountCB,
    AdminCB,
    DmCB,
    ExceptionCB,
    FilterCB,
    FlowCB,
    LoginCB,
    MenuCB,
    NumpadCB,
    OtherCB,
)
from app.userbots.runtime import GroupInfo
from app.utils.text import shorten

EXCEPTIONS_PAGE_SIZE = 8
ACCOUNTS_PAGE_SIZE = 20


def _single_column(builder: InlineKeyboardBuilder) -> InlineKeyboardMarkup:
    builder.adjust(1)
    return builder.as_markup()


def account_status_icon(account: Account, connected: bool) -> str:
    if account.status == AccountStatus.AUTH_ERROR:
        return "⚠️"
    if account.status == AccountStatus.SPAM_LIMITED:
        return "🚫"
    if not connected:
        return "🔴"
    return "🟢" if account.auto_message_enabled else "⚪"


# --------------------------------------------------------------------------- ana menü


def page_count(total: int, page_size: int) -> int:
    return max(1, -(-total // page_size))


def _account_button(account: Account, connected: bool) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text=f"{account_status_icon(account, connected)} {account.name}",
        callback_data=AccountCB(action="open", aid=account.id).pack(),
    )


def accounts_menu(accounts: Sequence[tuple[Account, bool]], page: int = 0) -> InlineKeyboardMarkup:
    """Sayfalı hesap listesi (Telegram bir klavyede en fazla 100 buton kabul eder)."""
    pages = page_count(len(accounts), ACCOUNTS_PAGE_SIZE)
    page = min(max(page, 0), pages - 1)
    start = page * ACCOUNTS_PAGE_SIZE
    rows = [
        [_account_button(account, connected)]
        for account, connected in accounts[start : start + ACCOUNTS_PAGE_SIZE]
    ]
    if pages > 1:
        nav = []
        if page > 0:
            nav.append(
                InlineKeyboardButton(
                    text="◀️", callback_data=MenuCB(action="accounts", page=page - 1).pack()
                )
            )
        nav.append(
            InlineKeyboardButton(
                text=f"{page + 1}/{pages}",
                callback_data=MenuCB(action="accounts", page=page).pack(),
            )
        )
        if page < pages - 1:
            nav.append(
                InlineKeyboardButton(
                    text="▶️", callback_data=MenuCB(action="accounts", page=page + 1).pack()
                )
            )
        rows.append(nav)
    rows.append(
        [
            InlineKeyboardButton(
                text=texts.BTN_ADD_ACCOUNT, callback_data=MenuCB(action="add").pack()
            )
        ]
    )
    rows.append(
        [InlineKeyboardButton(text=texts.BTN_INFO, callback_data=MenuCB(action="info").pack())]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def account_search_results(accounts: Sequence[tuple[Account, bool]]) -> InlineKeyboardMarkup:
    rows = [[_account_button(account, connected)] for account, connected in accounts]
    rows.append(
        [
            InlineKeyboardButton(
                text=texts.BTN_BACK_TO_LIST, callback_data=MenuCB(action="accounts").pack()
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def info_back() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=texts.BTN_BACK_ARROW, callback_data=MenuCB(action="accounts").pack()
                )
            ]
        ]
    )


def back_to_accounts() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=texts.BTN_BACK_TO_LIST, callback_data=MenuCB(action="accounts").pack()
                )
            ]
        ]
    )


# --------------------------------------------------------------------------- hesap paneli


def account_panel(account: Account) -> InlineKeyboardMarkup:
    aid = account.id
    builder = InlineKeyboardBuilder()
    builder.button(
        text=texts.BTN_AUTO_STOP if account.auto_message_enabled else texts.BTN_AUTO_START,
        callback_data=AccountCB(action="auto", aid=aid),
    )
    builder.button(
        text=texts.BTN_AUTO_SETTINGS, callback_data=AccountCB(action="auto_cfg", aid=aid)
    )
    builder.button(text=texts.BTN_DM_ALL, callback_data=AccountCB(action="dm_all", aid=aid))
    builder.button(
        text=texts.BTN_DM_REPLY_OFF if account.dm_auto_reply_enabled else texts.BTN_DM_REPLY_ON,
        callback_data=AccountCB(action="dm_toggle", aid=aid),
    )
    builder.button(text=texts.BTN_DM_SETTINGS, callback_data=AccountCB(action="dm_cfg", aid=aid))
    builder.button(text=texts.BTN_FILTERS, callback_data=FilterCB(action="list", aid=aid))
    builder.button(text=texts.BTN_EXCEPTIONS, callback_data=ExceptionCB(action="list", aid=aid))
    builder.button(text=texts.BTN_OTHER, callback_data=OtherCB(action="menu", aid=aid))
    builder.button(text=texts.BTN_HEALTH, callback_data=AccountCB(action="health", aid=aid))
    builder.button(text=texts.BTN_DELETE, callback_data=AccountCB(action="delete", aid=aid))
    builder.button(text=texts.BTN_BACK_TO_LIST, callback_data=MenuCB(action="accounts", aid=aid))
    return _single_column(builder)


def back_to_panel(aid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=texts.BTN_BACK, callback_data=AccountCB(action="open", aid=aid).pack()
                )
            ]
        ]
    )


def cancel_flow(aid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=texts.BTN_CANCEL, callback_data=FlowCB(aid=aid).pack())]
        ]
    )


def delete_confirm(aid: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=texts.BTN_DELETE_YES, callback_data=AccountCB(action="delete_yes", aid=aid))
    builder.button(text=texts.BTN_DELETE_NO, callback_data=AccountCB(action="open", aid=aid))
    builder.adjust(2)
    return builder.as_markup()


def health_menu(aid: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=texts.BTN_REFRESH, callback_data=AccountCB(action="health", aid=aid))
    builder.button(text=texts.BTN_RECONNECT, callback_data=AccountCB(action="reconnect", aid=aid))
    builder.button(text=texts.BTN_BACK, callback_data=AccountCB(action="open", aid=aid))
    builder.adjust(2, 1)
    return builder.as_markup()


# --------------------------------------------------------------------------- oturum açma


def share_phone_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=texts.BTN_SHARE_PHONE, request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def numpad() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for key in "123456789":
        builder.button(text=key, callback_data=NumpadCB(key=key))
    builder.button(text="⌫", callback_data=NumpadCB(key="del"))
    builder.button(text="0", callback_data=NumpadCB(key="0"))
    builder.button(text="✅", callback_data=NumpadCB(key="ok"))
    builder.button(text="🔄 Kodu Tekrar Gönder", callback_data=LoginCB(action="resend"))
    builder.button(text=texts.BTN_CANCEL, callback_data=LoginCB(action="cancel"))
    builder.adjust(3, 3, 3, 3, 2)
    return builder.as_markup()


def login_cancel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=texts.BTN_CANCEL, callback_data=LoginCB(action="cancel").pack()
                )
            ]
        ]
    )


# --------------------------------------------------------------------------- diğer özellikler


def other_menu(account: Account, cfg: AutoMessageConfig) -> InlineKeyboardMarkup:
    aid = account.id
    builder = InlineKeyboardBuilder()
    builder.button(
        text=texts.BTN_ARCHIVE.format(state=texts.on_off(cfg.include_archived)),
        callback_data=OtherCB(action="archive", aid=aid),
    )
    builder.button(
        text=texts.BTN_FALLBACK.format(state=texts.on_off(cfg.text_fallback_on_media_forbidden)),
        callback_data=OtherCB(action="fallback", aid=aid),
    )
    builder.button(
        text=texts.BTN_FORWARD_HEADER.format(
            state=texts.STATE_HIDDEN if cfg.hide_forward_source else texts.STATE_VISIBLE
        ),
        callback_data=OtherCB(action="fwd_header", aid=aid),
    )
    builder.button(
        text=texts.BTN_CONTACT.format(state=texts.on_off(cfg.has_contact)),
        callback_data=OtherCB(action="contact", aid=aid),
    )
    builder.button(
        text=texts.BTN_BATCH.format(size=cfg.batch_size),
        callback_data=OtherCB(action="batch", aid=aid),
    )
    builder.button(text=texts.BTN_PREVIEW, callback_data=OtherCB(action="preview", aid=aid))
    builder.button(text=texts.BTN_EXPORT, callback_data=OtherCB(action="export", aid=aid))
    builder.button(text=texts.BTN_BACK, callback_data=AccountCB(action="open", aid=aid))
    return _single_column(builder)


def contact_menu(aid: int, has_contact: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=texts.BTN_CONTACT_SET, callback_data=OtherCB(action="contact_set", aid=aid))
    if has_contact:
        builder.button(
            text=texts.BTN_CONTACT_REMOVE, callback_data=OtherCB(action="contact_rm", aid=aid)
        )
    builder.button(text=texts.BTN_BACK, callback_data=OtherCB(action="menu", aid=aid))
    return _single_column(builder)


def back_to_other(aid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=texts.BTN_BACK, callback_data=OtherCB(action="menu", aid=aid).pack()
                )
            ]
        ]
    )


# --------------------------------------------------------------------------- DM


def broadcast_confirm(aid: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=texts.BTN_BROADCAST_GO, callback_data=DmCB(action="go", aid=aid))
    builder.button(text=texts.BTN_CANCEL, callback_data=FlowCB(aid=aid))
    builder.adjust(2)
    return builder.as_markup()


def broadcast_running(aid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=texts.BTN_BROADCAST_STOP, callback_data=DmCB(action="stop", aid=aid).pack()
                )
            ]
        ]
    )


def dm_settings(account: Account, dm: DMAutoReplyConfig) -> InlineKeyboardMarkup:
    aid = account.id
    builder = InlineKeyboardBuilder()
    builder.button(
        text=texts.BTN_DM_REPLY_OFF if account.dm_auto_reply_enabled else texts.BTN_DM_REPLY_ON,
        callback_data=DmCB(action="toggle", aid=aid),
    )
    builder.button(text=texts.BTN_DM_SET_MESSAGE, callback_data=DmCB(action="set", aid=aid))
    builder.button(
        text=texts.BTN_DM_CONTACTS.format(state=texts.on_off(not dm.skip_contacts)),
        callback_data=DmCB(action="contacts", aid=aid),
    )
    builder.button(text=texts.BTN_BACK, callback_data=AccountCB(action="open", aid=aid))
    return _single_column(builder)


# --------------------------------------------------------------------------- filtreler


def filters_list(aid: int, filters: Sequence[ReplyFilter]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for reply_filter in filters:
        icon = "🟢" if reply_filter.is_active else "⏸"
        label = shorten(", ".join(reply_filter.keywords), 28)
        builder.button(
            text=f"{icon} {label} → {shorten(reply_filter.reply_text, 20)}",
            callback_data=FilterCB(action="view", aid=aid, fid=reply_filter.id),
        )
    builder.button(text=texts.BTN_FILTER_ADD, callback_data=FilterCB(action="add", aid=aid))
    builder.button(text=texts.BTN_BACK, callback_data=AccountCB(action="open", aid=aid))
    return _single_column(builder)


def filter_detail(aid: int, reply_filter: ReplyFilter) -> InlineKeyboardMarkup:
    fid = reply_filter.id
    builder = InlineKeyboardBuilder()
    builder.button(
        text=texts.BTN_FILTER_MATCH.format(match=texts.MATCH_NAMES[reply_filter.match_type]),
        callback_data=FilterCB(action="match", aid=aid, fid=fid),
    )
    builder.button(
        text=texts.BTN_FILTER_COOLDOWN.format(cooldown=reply_filter.cooldown_sec),
        callback_data=FilterCB(action="cooldown", aid=aid, fid=fid),
    )
    builder.button(
        text=texts.BTN_FILTER_PAUSE if reply_filter.is_active else texts.BTN_FILTER_RESUME,
        callback_data=FilterCB(action="toggle", aid=aid, fid=fid),
    )
    builder.button(
        text=texts.BTN_FILTER_DELETE, callback_data=FilterCB(action="delete", aid=aid, fid=fid)
    )
    builder.button(text=texts.BTN_BACK, callback_data=FilterCB(action="list", aid=aid))
    return _single_column(builder)


# --------------------------------------------------------------------------- istisnalar


def exceptions_list(aid: int, chats: Sequence[tuple[int, str]]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for chat_id, title in chats[:40]:
        builder.button(
            text=f"❌ {shorten(title, 40)}",
            callback_data=ExceptionCB(action="rm", aid=aid, cid=chat_id),
        )
    builder.button(text=texts.BTN_EXC_PICK, callback_data=ExceptionCB(action="pick", aid=aid))
    builder.button(text=texts.BTN_EXC_MANUAL, callback_data=ExceptionCB(action="manual", aid=aid))
    builder.button(text=texts.BTN_BACK, callback_data=AccountCB(action="open", aid=aid))
    return _single_column(builder)


def exceptions_picker(
    aid: int, groups: Sequence[GroupInfo], selected: set[int], page: int
) -> InlineKeyboardMarkup:
    pages = max(1, -(-len(groups) // EXCEPTIONS_PAGE_SIZE))
    page = min(max(page, 0), pages - 1)
    start = page * EXCEPTIONS_PAGE_SIZE
    rows: list[list[InlineKeyboardButton]] = []
    for group in groups[start : start + EXCEPTIONS_PAGE_SIZE]:
        mark = "✅" if group.chat_id in selected else "▫️"
        archived = " 📁" if group.archived else ""
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{mark} {shorten(group.title, 38)}{archived}",
                    callback_data=ExceptionCB(
                        action="tog", aid=aid, page=page, cid=group.chat_id
                    ).pack(),
                )
            ]
        )
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(
            InlineKeyboardButton(
                text="◀️", callback_data=ExceptionCB(action="pick", aid=aid, page=page - 1).pack()
            )
        )
    nav.append(
        InlineKeyboardButton(
            text=f"{page + 1}/{pages}",
            callback_data=ExceptionCB(action="pick", aid=aid, page=page).pack(),
        )
    )
    if page < pages - 1:
        nav.append(
            InlineKeyboardButton(
                text="▶️", callback_data=ExceptionCB(action="pick", aid=aid, page=page + 1).pack()
            )
        )
    rows.append(nav)
    rows.append(
        [
            InlineKeyboardButton(
                text=texts.BTN_REFRESH,
                callback_data=ExceptionCB(action="refresh", aid=aid, page=page).pack(),
            ),
            InlineKeyboardButton(
                text=texts.BTN_BACK, callback_data=ExceptionCB(action="list", aid=aid).pack()
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


# --------------------------------------------------------------------------- admin


def admin_new_user(user_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=texts.BTN_ALLOW, callback_data=AdminCB(action="allow", uid=user_id))
    builder.button(text=texts.BTN_BAN, callback_data=AdminCB(action="ban", uid=user_id))
    builder.adjust(2)
    return builder.as_markup()
