# states.py
from aiogram.fsm.state import StatesGroup, State


class RegistrationStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_phone = State()
    waiting_for_address = State()
    waiting_for_organization = State()


class OrderStates(StatesGroup):
    waiting_for_day = State()
    waiting_for_time = State()
    confirm_order = State()


class EditDataStates(StatesGroup):
    choose_field = State()
    waiting_for_new_phone = State()
    waiting_for_new_address = State()
    waiting_for_new_name = State()
    waiting_for_new_organization = State()


class AdminStates(StatesGroup):
    waiting_user_name = State()
    waiting_user_phone = State()
    waiting_user_address = State()
    waiting_user_organization = State()
    waiting_order_time = State()


class DirectMessageStates(StatesGroup):
    waiting_for_text = State()


