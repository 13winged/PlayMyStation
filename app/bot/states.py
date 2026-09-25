"""FSM-состояния бота."""
from aiogram.fsm.state import State, StatesGroup


class YandexAuth(StatesGroup):
    waiting_token = State()
