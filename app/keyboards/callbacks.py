"""Inline buton callback verileri (Telegram sınırı: 64 bayt)."""

from aiogram.filters.callback_data import CallbackData


class MenuCB(CallbackData, prefix="m"):
    action: str  # accounts | add | info


class AccountCB(CallbackData, prefix="a"):
    action: str
    aid: int


class OtherCB(CallbackData, prefix="o"):
    action: str
    aid: int


class DmCB(CallbackData, prefix="d"):
    action: str
    aid: int


class FilterCB(CallbackData, prefix="f"):
    action: str
    aid: int
    fid: int = 0


class ExceptionCB(CallbackData, prefix="e"):
    action: str
    aid: int
    page: int = 0
    cid: int = 0


class NumpadCB(CallbackData, prefix="n"):
    key: str  # 0-9 | del | ok


class LoginCB(CallbackData, prefix="l"):
    action: str  # resend | cancel


class AdminCB(CallbackData, prefix="adm"):
    action: str  # allow | ban
    uid: int


class FlowCB(CallbackData, prefix="c"):
    """Sihirbazlardaki 'Vazgeç' butonu: durumu temizleyip panele döner."""

    aid: int
