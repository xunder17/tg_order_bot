import re

from aiogram import Router
from aiogram import types, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from sqlalchemy import select

from db import async_sessionmaker, User
from states import RegistrationStates
from aiogram.utils.keyboard import ReplyKeyboardBuilder

router = Router()


def main_menu_keyboard() -> types.ReplyKeyboardMarkup:
    kb = ReplyKeyboardBuilder()
    kb.button(text="🛒 Оформить заказ")
    kb.button(text="✉️ Написать напрямую")
    kb.button(text="✏️ Изменить данные")
    kb.adjust(1)
    return kb.as_markup(resize_keyboard=True)


@router.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    async with async_sessionmaker() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
    if user is None:
        # Создаем inline-клавиатуру с кнопкой "Старт"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚀 Старт", callback_data="start_work")]
        ])
        await message.answer(
            "✨ Добро пожаловать в нашего умного бота! ✨\n\nНажмите кнопку <b>Старт</b>, чтобы начать регистрацию.",
            parse_mode="HTML",
            reply_markup=keyboard
        )
    else:
        await message.answer(
            "👋 Снова привет! Воспользуйся меню!",
            reply_markup=main_menu_keyboard(),
            parse_mode="HTML"
        )

@router.callback_query(lambda callback: callback.data == "start_work")
async def start_work_handler(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()  # Убираем "часики" в Telegram
    # Обновляем сообщение с инструкцией для регистрации
    await callback.message.edit_text(
        "Пожалуйста, введите своё имя:",
        parse_mode="HTML"
    )
    await state.set_state(RegistrationStates.waiting_for_name)


def validate_phone(phone: str) -> bool:
    return bool(re.match(r'^\+?[1-9]\d{6,14}$', phone.strip()))


def validate_name(name: str) -> bool:
    return 2 <= len(name.strip()) <= 50 and re.match(r'^[a-zA-Zа-яА-Я\s-]+$', name.strip())


def validate_address(address: str) -> bool:
    return 5 <= len(address.strip()) <= 200


@router.message(RegistrationStates.waiting_for_phone)
async def reg_get_phone(message: types.Message, state: FSMContext):
    phone = message.text.strip()
    if not validate_phone(phone):
        await message.answer("❌ Неверный формат номера. Используйте: +79991234567 (от 7 до 15 цифр).")
        return
    await state.update_data(phone=phone)
    await message.answer("Введи адрес:")
    await state.set_state(RegistrationStates.waiting_for_address)


@router.message(RegistrationStates.waiting_for_name)
async def reg_get_name(message: types.Message, state: FSMContext):
    name = message.text.strip()
    if not validate_name(name):
        await message.answer("❌ Имя должно быть от 2 до 50 символов, только буквы, пробелы или дефис.")
        return
    await state.update_data(name=name)
    await message.answer("Отлично! Теперь введи номер телефона:")
    await state.set_state(RegistrationStates.waiting_for_phone)


@router.message(RegistrationStates.waiting_for_address)
async def reg_get_address(message: types.Message, state: FSMContext):
    address = message.text.strip()
    if not validate_address(address):
        await message.answer("❌ Адрес должен быть от 5 до 200 символов.")
        return
    await state.update_data(address=address)
    await message.answer("Укажи название организации (если есть). Если нет, напиши 'Нет':")
    await state.set_state(RegistrationStates.waiting_for_organization)


@router.message(RegistrationStates.waiting_for_organization)
async def reg_get_organization(message: types.Message, state: FSMContext):
    data = await state.get_data()
    name = data["name"]
    phone = data["phone"]
    address = data["address"]
    organization = message.text

    tg_id = message.from_user.id

    async with async_sessionmaker() as session:
        new_user = User(
            telegram_id=tg_id,
            name=name,
            phone=phone,
            address=address,
            organization = "Нет" if organization.lower() == "нет" else organization
        )
        session.add(new_user)
        await session.commit()

    await message.answer(
        f"✨ <b>Отлично, {name}!</b> Ваши данные успешно сохранены! ✨\n\n"
        f"📞 <b>Телефон:</b> {phone}\n"
        f"🏠 <b>Адрес:</b> {address}\n"
        f"🏢 <b>Организация:</b> {organization}\n\n"
        "✅ Добро пожаловать в главное меню!",
        reply_markup=main_menu_keyboard(),
        parse_mode="HTML"
    )

    await state.clear()
