"""Çok adımlı akışların FSM durumları."""

from aiogram.fsm.state import State, StatesGroup


class LoginStates(StatesGroup):
    name = State()
    phone = State()
    code = State()
    password = State()


class AutoMsgStates(StatesGroup):
    message = State()
    delay = State()
    cycle = State()


class OtherStates(StatesGroup):
    contact = State()
    batch_size = State()


class DMStates(StatesGroup):
    broadcast_message = State()
    broadcast_confirm = State()
    reply_message = State()


class FilterStates(StatesGroup):
    keywords = State()
    reply = State()


class ExceptionStates(StatesGroup):
    manual = State()
