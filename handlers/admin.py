import re
import logging

from datetime import datetime, timedelta

from aiogram import types, F
from aiogram.filters import Command
from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy import delete

from db import async_sessionmaker, Order, User
from config import ADMIN_IDS
from states import AdminStates
from zoneinfo import ZoneInfo

MOSCOW_TZ = ZoneInfo("Europe/Moscow")

router = Router()

POSSIBLE_STATUSES = ["Новая (От пользователя)", "Новая (От Админа)", "В работе", "Исполнено"]


def admin_main_keyboard() -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Добавить заявку", callback_data="admin_add_order")
    builder.button(text="Список заявок", callback_data="admin_orders")
    builder.button(text="Помощь", callback_data="admin_help")
    builder.adjust(1)
    return builder.as_markup()


def admin_orders_button() -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Список заявок", callback_data="admin_orders")
    builder.adjust(1)
    return builder.as_markup()


def is_admin(user_id: int) -> bool:
    try:
        admin_ids_int = [int(x.strip()) for x in ADMIN_IDS if x.strip()]
    except ValueError:
        admin_ids_int = []
    return user_id in admin_ids_int


@router.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав администратора.")
        return

    await message.answer(
        "🔐 *Админ-панель*",
        parse_mode="Markdown",
        reply_markup=admin_main_keyboard()
    )


@router.callback_query(F.data == "admin_add_order")
async def start_add_order(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "Введите <b>имя пользователя</b> для новой заявки:",
        parse_mode="HTML"
    )
    await state.set_state(AdminStates.waiting_user_name)


@router.message(AdminStates.waiting_user_name)
async def process_user_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("Введите <b>номер телефона</b> пользователя:")
    await state.set_state(AdminStates.waiting_user_phone)


@router.message(AdminStates.waiting_user_phone)
async def process_user_phone(message: types.Message, state: FSMContext):
    if not re.match(r'^\+?[1-9]\d{6,14}$', message.text):
        await message.answer("❌ Неверный формат номера. Введите снова:")
        return
        
    await state.update_data(phone=message.text)
    await message.answer("Введите <b>адрес</b> пользователя:")
    await state.set_state(AdminStates.waiting_user_address)


@router.message(AdminStates.waiting_user_address)
async def process_user_address(message: types.Message, state: FSMContext):
    await state.update_data(address=message.text)
    await message.answer("Введите <b>предпочитаемое время</b> для заявки:")
    await state.set_state(AdminStates.waiting_order_time)


@router.message(AdminStates.waiting_order_time)
async def process_order_time(message: types.Message, state: FSMContext):
    data = await state.get_data()

    async with async_sessionmaker() as session:
        new_user = User(
            name=data['name'],
            phone=data['phone'],
            address=data['address'],
            telegram_id=None,
            username=None
        )
        session.add(new_user)
        await session.commit()
        await session.refresh(new_user)

        new_order = Order(
            user_id=new_user.id,
            status="Новая (От Админа)",
            preferred_time=message.text
        )
        session.add(new_order)
        await session.commit()
        await session.refresh(new_order)

    await message.answer(
        f"✅ Заявка *#{new_order.id}* создана!\n"
        f"▪️ Пользователь: {new_user.name}\n"
        f"▪️ Телефон: {new_user.phone}\n"
        f"▪️ Время: {message.text}",
        parse_mode="Markdown",
        reply_markup=admin_orders_button()
    )
    await state.clear()


@router.callback_query(F.data == "admin_orders")
async def show_orders(callback: types.CallbackQuery, state: FSMContext):
    async with async_sessionmaker() as session:
        orders = await session.execute(
            select(Order).options(selectinload(Order.user)).order_by(Order.id.desc()))
        orders = orders.scalars().all()

    if not orders:
        await callback.message.edit_text("📭 Список заявок пуст")
        return

    await state.update_data(all_orders=orders, current_page=0)
    await display_orders_page(callback, state)


async def display_orders_page(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    all_orders = data.get("all_orders", [])
    current_page = data.get("current_page", 0)
    orders_per_page = 10
    start_index = current_page * orders_per_page
    end_index = start_index + orders_per_page
    current_orders = all_orders[start_index:end_index]

    builder = InlineKeyboardBuilder()
    for order in current_orders:
        # Исправление времени с учетом часового пояса Москвы
        created_at_moscow = order.created_at.replace(tzinfo=ZoneInfo("UTC")).astimezone(MOSCOW_TZ)
        builder.button(
            text=f"#{order.id} - {order.status} ({created_at_moscow.strftime('%Y-%m-%d %H:%M')})",
            callback_data=f"order_detail_{order.id}"
        )

    if current_page > 0:
        builder.button(text="⬅️ Назад", callback_data="prev_page")
    if end_index < len(all_orders):
        builder.button(text="Вперед ➡️", callback_data="next_page")

    builder.button(text="↩ Назад", callback_data="admin_back")
    builder.adjust(1)

    await callback.message.edit_text(
        f"📋 *Последние заявки (страница {current_page + 1}):*",
        parse_mode="Markdown",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data == "prev_page")
async def prev_page(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    current_page = data.get("current_page", 0)
    if current_page > 0:
        await state.update_data(current_page=current_page - 1)
        await display_orders_page(callback, state)


@router.callback_query(F.data == "next_page")
async def next_page(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    current_page = data.get("current_page", 0)
    await state.update_data(current_page=current_page + 1)
    await display_orders_page(callback, state)


@router.callback_query(F.data.startswith("order_detail_"))
async def order_detail(callback: types.CallbackQuery):
    order_id_str = callback.data.split("_")[-1]
    if not order_id_str.isdigit():
        await callback.answer("Неверный формат ID заявки.")
        return

    order_id = int(order_id_str)

    async with async_sessionmaker() as session:
        order = await session.get(Order, order_id, options=[selectinload(Order.user)])
        if not order:
            await callback.message.edit_text("Заявка не найдена или была удалена.")
            return

    # Создаем две отдельных клавиатуры
    status_buttons = InlineKeyboardBuilder()
    control_buttons = InlineKeyboardBuilder()
    
    current_status = order.status

    # Кнопки для смены статуса
    for status in POSSIBLE_STATUSES:
        if status != current_status:
            status_buttons.button(
                text=status,
                callback_data=f"set_status_{order.id}_{status}"
            )
    
    # Кнопки управления
    control_buttons.button(text="🗑 Удалить", callback_data=f"confirm_delete_{order.id}")
    control_buttons.button(text="↩ К списку", callback_data="admin_orders")
    control_buttons.adjust(2)

    # Объединяем клавиатуры
    full_keyboard = InlineKeyboardBuilder()
    full_keyboard.attach(status_buttons)
    full_keyboard.attach(control_buttons)
    full_keyboard.adjust(2, repeat=True)

    # Форматирование информации о пользователе
    user_info = (
        f"▪ Имя: {order.user.name if order.user else 'N/A'}\n"
        f"▪ Телефон: {order.user.phone if order.user else 'N/A'}\n"
        f"▪ Адрес: {order.user.address if order.user else 'N/A'}\n"
        f"▪ Организация: {order.user.organization if order.user else 'N/A'}\n"
    )

    # Форматирование времени с учетом часового пояса
    created_at_moscow = order.created_at.replace(tzinfo=ZoneInfo("UTC")).astimezone(MOSCOW_TZ)
    completed_time = (
        order.completed_at.replace(tzinfo=ZoneInfo("UTC")).astimezone(MOSCOW_TZ).strftime('%d.%m.%Y %H:%M')
        if order.completed_at
        else "Не завершена"
    )

    status_text = {
        "Новая (От пользователя)": "🟡 Новая (От пользователя)",
        "Новая (От Админа)": "🟠 Новая (От Админа)",
        "В работе": "🟢 В работе",
        "Исполнено": "🔵 Исполнено"
    }.get(order.status, order.status)

    await callback.message.edit_text(
        f"<b>📄 Заявка #{order.id}</b>\n\n"
        f"<b>👤 Данные клиента:</b>\n{user_info}\n"
        f"<b>📦 Детали заказа:</b>\n"
        f"▪ Предпочитаемое время: {order.preferred_time}\n"
        f"▪ Статус: {status_text}\n"
        f"▪ Создана: {created_at_moscow.strftime('%d.%m.%Y %H:%M')}\n"
        f"▪ Завершена: {completed_time}",
        parse_mode="HTML",
        reply_markup=full_keyboard.as_markup()
    )


@router.callback_query(F.data.startswith("confirm_delete_"))
async def confirm_delete(callback: types.CallbackQuery):
    order_id = int(callback.data.split("_")[-1])
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, удалить", callback_data=f"delete_order_{order_id}")
    builder.button(text="❌ Отмена", callback_data=f"order_detail_{order_id}")
    builder.adjust(2)
    
    await callback.message.edit_text(
        f"⚠️ Вы уверены, что хотите удалить заявку #{order_id}?",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data.startswith("delete_order_"))
async def delete_order_handler(callback: types.CallbackQuery, state: FSMContext):
    order_id = int(callback.data.split("_")[-1])
    async with async_sessionmaker() as session:
        order = await session.get(Order, order_id)
        if order:
            await session.delete(order)
            await session.commit()
    
    # Уведомляем администратора
    await callback.message.edit_text(
        f"✅ Заявка #{order_id} успешно удалена!",
        reply_markup=admin_orders_button()
    )
    
    # Обновляем список заказов
    await show_orders(callback, state)


@router.callback_query(F.data.startswith("set_status_"))
async def set_order_status(callback: types.CallbackQuery):
    try:
        parts = callback.data.split("_")
        if len(parts) < 3:
            await callback.answer("❌ Ошибка: неверный формат данных.")
            return

        order_id = int(parts[2])
        new_status = "_".join(parts[3:])

        async with async_sessionmaker() as session:
            order = await session.get(Order, order_id)
            if not order:
                await callback.answer("Заявка не найдена.")
                return

            order.status = new_status

            if new_status == "Исполнено" and not order.completed_at:
                order.completed_at = datetime.utcnow()
            else:
                order.completed_at = None

            await session.commit()

        builder = InlineKeyboardBuilder()
        builder.button(text="↩ Назад", callback_data="admin_orders")
        builder.adjust(1)

        await callback.message.edit_text(
            f"✅ Статус заявки #{order_id} изменен на: {new_status}\n"
            f"🕒 Время изменения: {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}",
            reply_markup=builder.as_markup()
        )

    except Exception as e:
        logging.error(f"Ошибка при изменении статуса заявки: {e}")
        await callback.answer("❌ Произошла ошибка при изменении статуса.")


@router.callback_query(F.data == "admin_help")
async def show_admin_help(callback: types.CallbackQuery):
    help_text = (
        "🛠 *Справка для администратора*\n\n"
        "Здесь вы можете управлять заявками и пользователями.\n\n"
        "🔹 *Как работать с ботом:*\n"
        "1. Используйте кнопки в админ-панели для управления заявками.\n"
        "2. Для добавления заявки введите данные пользователя и предпочитаемое время.\n"
        "3. Вы можете изменять статус заявок через кнопки в списке заявок.\n\n"
        "Если возникнут вопросы, обратитесь к разработчику."
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="↩ Назад", callback_data="admin_back")

    await callback.message.edit_text(
        help_text,
        parse_mode="Markdown",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data == "admin_back")
async def back_to_admin_menu(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "🔐 *Админ-панель*",
        parse_mode="Markdown",
        reply_markup=admin_main_keyboard()
    )


async def cleanup_old_orders():
    try:
        twenty_four_hours_ago = datetime.utcnow() - timedelta(hours=24)
        async with async_sessionmaker() as session:
            result = await session.execute(
                delete(Order)
                .where(Order.status == "Исполнено")
                .where(Order.completed_at < twenty_four_hours_ago)
            )
            deleted_count = result.rowcount
            await session.commit()
            logging.info(f"Deleted {deleted_count} orders older than 24 hours.")
    except Exception as e:
        logging.error(f"Error during cleanup_old_orders: {e}")


async def cleanup_old_orders():
    try:
        twenty_four_hours_ago = datetime.utcnow() - timedelta(hours=24)
        async with async_sessionmaker() as session:
            result = await session.execute(
                delete(Order)
                .where(Order.status == "Исполнено")
                .where(Order.completed_at < twenty_four_hours_ago)
            )
            deleted_count = result.rowcount
            await session.commit()
            logging.info(f"Deleted {deleted_count} orders older than 24 hours.")
    except Exception as e:
        logging.error(f"Error during cleanup_old_orders: {e}")