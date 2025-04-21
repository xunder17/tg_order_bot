import re
import logging

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import types, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from sqlalchemy import select, delete
from sqlalchemy.orm import selectinload

from db import async_sessionmaker, Order, User
from config import ADMIN_IDS
from states import AdminStates

MOSCOW_TZ = ZoneInfo("Europe/Moscow")
router = Router()

POSSIBLE_STATUSES = [
    "Новая (От пользователя)",
    "Новая (От Админа)",
    "В работе",
    "Исполнено",
]


def admin_main_keyboard() -> types.InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Добавить заявку", callback_data="admin_add_order")
    kb.button(text="Активные заявки", callback_data="admin_orders_active")
    kb.button(text="Исполненные заявки", callback_data="admin_orders_done")
    kb.button(text="Помощь", callback_data="admin_help")
    kb.adjust(1)
    return kb.as_markup()


def admin_back_to_main() -> types.InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="↩ Назад в меню", callback_data="admin_back")
    kb.adjust(1)
    return kb.as_markup()


def admin_orders_button() -> types.InlineKeyboardMarkup:
    # Используется в handlers/order.py для ссылки на активные заявки
    kb = InlineKeyboardBuilder()
    kb.button(text="Список заявок", callback_data="admin_orders_active")
    kb.adjust(1)
    return kb.as_markup()


def is_admin(user_id: int) -> bool:
    try:
        return user_id in [int(x) for x in ADMIN_IDS if x.strip().isdigit()]
    except Exception:
        return False


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
    preferred_time = message.text.strip()

    async with async_sessionmaker() as session:
        async with session.begin():
            new_user = User(
                name=data['name'],
                phone=data['phone'],
                address=data['address'],
                telegram_id=None,
                username=None
            )
            session.add(new_user)
            await session.flush()  # чтобы получить new_user.id

            new_order = Order(
                user_id=new_user.id,
                status="Новая (От Админа)",
                preferred_time=preferred_time
            )
            session.add(new_order)
        # транзакция автоматически зафиксирована

        await session.refresh(new_user)
        await session.refresh(new_order)

    await message.answer(
        f"✅ Заявка *#{new_order.id}* создана!\n"
        f"▪️ Пользователь: {new_user.name}\n"
        f"▪️ Телефон: {new_user.phone}\n"
        f"▪️ Время: {preferred_time}",
        parse_mode="Markdown",
        reply_markup=admin_back_to_main()
    )
    await state.clear()


@router.callback_query(F.data.startswith("admin_orders"))
async def show_orders(callback: types.CallbackQuery, state: FSMContext):
    filter_done = callback.data == "admin_orders_done"
    async with async_sessionmaker() as session:
        q = select(Order).options(selectinload(Order.user))
        if filter_done:
            q = q.where(Order.status == "Исполнено")
        else:
            q = q.where(Order.status != "Исполнено")
        q = q.order_by(Order.id.desc())
        result = await session.execute(q)
        orders = result.scalars().all()

    if not orders:
        text = "📭 Список исполненных заявок пуст" if filter_done else "📭 Список активных заявок пуст"
        await callback.message.edit_text(text, reply_markup=admin_back_to_main())
        return

    await state.update_data(all_orders=orders, current_page=0)
    await display_orders_page(callback, state)


async def display_orders_page(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    orders = data["all_orders"]
    page = data.get("current_page", 0)
    per_page = 10
    chunk = orders[page*per_page:(page+1)*per_page]

    kb = InlineKeyboardBuilder()
    for o in chunk:
        ts = o.created_at.replace(tzinfo=ZoneInfo("UTC")).astimezone(MOSCOW_TZ)
        kb.button(
            text=f"#{o.id} {o.status} ({ts:%Y-%m-%d %H:%M})",
            callback_data=f"order_detail_{o.id}"
        )
    if page > 0:
        kb.button(text="⬅️ Назад", callback_data="prev_page")
    if (page+1)*per_page < len(orders):
        kb.button(text="Вперед ➡️", callback_data="next_page")

    kb.button(text="↩ Назад в меню", callback_data="admin_back")
    kb.adjust(1)

    total = (len(orders)-1)//per_page + 1
    await callback.message.edit_text(
        f"📋 Заявки (страница {page+1}/{total}):",
        parse_mode="Markdown",
        reply_markup=kb.as_markup()
    )


@router.callback_query(F.data == "prev_page")
async def prev_page(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if data["current_page"] > 0:
        await state.update_data(current_page=data["current_page"] - 1)
        await display_orders_page(callback, state)


@router.callback_query(F.data == "next_page")
async def next_page(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.update_data(current_page=data.get("current_page", 0) + 1)
    await display_orders_page(callback, state)


@router.callback_query(F.data.startswith("order_detail_"))
async def order_detail(callback: types.CallbackQuery):
    order_id = int(callback.data.rsplit("_", 1)[1])
    async with async_sessionmaker() as session:
        order = await session.get(Order, order_id, options=[selectinload(Order.user)])

    if not order:
        await callback.message.edit_text("Заявка не найдена.", reply_markup=admin_back_to_main())
        return

    # кнопки смены статуса
    kb_status = InlineKeyboardBuilder()
    for status in POSSIBLE_STATUSES:
        if status != order.status:
            kb_status.button(text=status, callback_data=f"set_status_{order.id}_{status}")

    # кнопки управления
    kb_ctrl = InlineKeyboardBuilder()
    kb_ctrl.button(text="🗑 Удалить", callback_data=f"confirm_delete_{order.id}")
    kb_ctrl.button(text="↩ К списку", callback_data="admin_orders_active")
    kb_ctrl.adjust(2)

    kb = InlineKeyboardBuilder()
    kb.attach(kb_status)
    kb.attach(kb_ctrl)
    kb.adjust(2, repeat=True)

    ts = order.created_at.replace(tzinfo=ZoneInfo("UTC")).astimezone(MOSCOW_TZ)
    completed = (
        order.completed_at.replace(tzinfo=ZoneInfo("UTC")).astimezone(MOSCOW_TZ).strftime('%d.%m.%Y %H:%M')
        if order.completed_at else "Не завершена"
    )
    status_text = {
        "Новая (От пользователя)": "🟡 Новая (От пользователя)",
        "Новая (От Админа)":    "🟠 Новая (От Админа)",
        "В работе":             "🟢 В работе",
        "Исполнено":            "🔵 Исполнено"
    }.get(order.status, order.status)

    user = order.user or User(name="N/A", phone="N/A", address="N/A", organization="N/A")
    info = (
        f"▪ Имя: {user.name}\n"
        f"▪ Телефон: {user.phone}\n"
        f"▪ Адрес: {user.address}\n"
        f"▪ Организация: {user.organization}\n"
    )

    await callback.message.edit_text(
        f"<b>📄 Заявка #{order.id}</b>\n\n"
        f"<b>👤 Клиент:</b>\n{info}\n"
        f"<b>📦 Детали:</b>\n"
        f"▪ Время: {order.preferred_time}\n"
        f"▪ Статус: {status_text}\n"
        f"▪ Создано: {ts:%d.%m.%Y %H:%M}\n"
        f"▪ Завершено: {completed}",
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )


@router.callback_query(F.data.startswith("confirm_delete_"))
async def confirm_delete(callback: types.CallbackQuery):
    order_id = int(callback.data.rsplit("_", 1)[1])
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Да, удалить", callback_data=f"delete_order_{order_id}")
    kb.button(text="❌ Отмена", callback_data=f"order_detail_{order_id}")
    kb.adjust(2)
    await callback.message.edit_text(
        f"⚠️ Удалить заявку #{order_id}?",
        reply_markup=kb.as_markup()
    )


@router.callback_query(F.data.startswith("delete_order_"))
async def delete_order_handler(callback: types.CallbackQuery, state: FSMContext):
    order_id = int(callback.data.rsplit("_", 1)[1])
    async with async_sessionmaker() as session:
        async with session.begin():
            o = await session.get(Order, order_id)
            if o:
                await session.delete(o)
    await callback.message.edit_text(
        f"✅ Заявка #{order_id} удалена.",
        reply_markup=admin_back_to_main()
    )
    await show_orders(callback, state)


@router.callback_query(F.data.startswith("set_status_"))
async def set_order_status(callback: types.CallbackQuery):
    payload = callback.data[len("set_status_"):]          # e.g. "2_Исполнено"
    order_id_str, new_status = payload.split("_", 1)
    try:
        order_id = int(order_id_str)
    except ValueError:
        await callback.answer("❌ Неверный ID заявки.")
        return

    async with async_sessionmaker() as session:
        order = await session.get(Order, order_id)
        if not order:
            await callback.answer("❌ Заявка не найдена.")
            return
        order.status = new_status
        order.completed_at = datetime.utcnow() if new_status == "Исполнено" else None
        await session.commit()

    kb = InlineKeyboardBuilder()
    kb.button(text="↩ Назад к активным", callback_data="admin_orders_active")
    kb.adjust(1)
    await callback.message.edit_text(
        f"✅ Статус #{order_id} -> {new_status}",
        reply_markup=kb.as_markup()
    )


@router.callback_query(F.data == "admin_help")
async def show_admin_help(callback: types.CallbackQuery):
    text = (
        "🛠 *Справка для администратора*\n\n"
        "🔸 Добавить заявку\n"
        "🔸 Просмотреть активные / исполненные заявки\n"
        "🔸 Сменить статус или удалить заявку\n"
    )
    await callback.message.edit_text(
        text,
        parse_mode="Markdown",
        reply_markup=admin_back_to_main()
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
        cutoff = datetime.utcnow() - timedelta(hours=24)
        async with async_sessionmaker() as session:
            await session.execute(
                delete(Order)
                .where(Order.status == "Исполнено")
                .where(Order.completed_at < cutoff)
            )
            await session.commit()
        logging.info("Очистка старых исполненных заявок завершена.")
    except Exception:
        logging.exception("Ошибка в cleanup_old_orders")
