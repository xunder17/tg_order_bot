from aiogram import Router
from aiogram import types, F
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

from sqlalchemy import select
from handlers.admin import admin_orders_button
from db import async_sessionmaker, Order, User
from states import OrderStates, EditDataStates, DirectMessageStates
from config import ADMIN_IDS
from datetime import datetime, time
from zoneinfo import ZoneInfo
import logging

router = Router()

MOSCOW_TZ = ZoneInfo("Europe/Moscow")


async def main_menu_keyboard(user_id: int) -> types.ReplyKeyboardMarkup:
    kb = ReplyKeyboardBuilder()
    kb.button(text="🛒 Оформить заказ")
    kb.button(text="✉️ Написать напрямую")
    kb.button(text="✏️ Изменить данные")

    # Проверяем наличие активного заказа
    async with async_sessionmaker() as session:
        active_order = await session.execute(
            select(Order)
            .join(User)
            .where(
                User.telegram_id == user_id,
                Order.status != "Исполнено"
            )
        )
        if active_order.scalar_one_or_none():
            kb.button(text="❌ Отменить заказ")

    kb.adjust(1)
    return kb.as_markup(resize_keyboard=True)


@router.message(lambda message: "Оформить заказ" in message.text)
async def make_order(message: types.Message, state: FSMContext):
    # Получаем данные пользователя из базы данных
    async with async_sessionmaker() as session:
        user_in_db = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = user_in_db.scalar_one_or_none()

    # Форматируем информацию о пользователе
    user_info = "📋 <b>Ваши данные:</b>\n\n"
    if user:
        user_info += f"👤 <b>Имя:</b> {user.name if user.name else 'Не указано'}\n"
        user_info += f"📞 <b>Телефон:</b> {user.phone if user.phone else 'Не указано'}\n"
        user_info += f"🏠 <b>Адрес:</b> {user.address if user.address else 'Не указано'}\n"
        user_info += f"🏢 <b>Организация:</b> {user.organization if user.organization else 'Не указано'}\n"
    else:
        user_info += "⚠️ Данные пользователя не найдены\n"

    # Создаем клавиатуру
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить", callback_data="confirm_order")
    builder.button(text="❌ Отмена", callback_data="cancel_order")
    builder.adjust(2)

    # Отправляем сообщение с данными
    await message.answer(
        f"🛒 <b>Оформление заказа</b>\n\n"
        f"{user_info}\n"
        f"Проверьте данные и подтвердите заказ:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(OrderStates.confirm_order)


@router.callback_query(OrderStates.confirm_order, F.data == "cancel_order")
async def cancel_order_handler(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Оформление заказа отменено.")
    await state.clear()


@router.callback_query(OrderStates.confirm_order, F.data == "confirm_order")
async def confirm_order_handler(callback: types.CallbackQuery, state: FSMContext):
    now = datetime.now(MOSCOW_TZ)
    cutoff_time = time(11, 30)
    current_time = now.time()

    async with async_sessionmaker() as session:
        # Проверяем, есть ли у пользователя активный заказ
        active_order = await session.execute(
            select(Order)
            .join(User)
            .where(
                User.telegram_id == callback.from_user.id,
                Order.status != "Исполнено"
            )
        )
        active_order = active_order.scalar_one_or_none()

        if active_order:
            await callback.message.edit_text(
                "❌ У вас уже есть активный заказ. Вы не можете оформить новый, пока не завершите текущий.",
                parse_mode="HTML"
            )
            return

        # Получаем или создаем пользователя
        user = await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        user = user.scalar_one_or_none()

        if not user:
            await callback.message.edit_text("❌ Ошибка: пользователь не найден")
            await state.clear()
            return

        # Обновляем username, если изменился
        if callback.from_user.username != user.username:
            user.username = callback.from_user.username
            await session.commit()

        # Определяем время доставки
        if current_time <= cutoff_time:
            delivery_day = "Сегодня"
            pickup_text = "Мы заберём оборудование сегодня в ближайшее время!"
        else:
            delivery_day = "Завтра"
            pickup_text = "Мы заберём оборудование завтра с 8:00 до 12:00."

        # Создаем новый заказ
        new_order = Order(
            user_id=user.id,
            status="Новая (От пользователя)",
            preferred_time=delivery_day
        )
        session.add(new_order)
        await session.commit()
        await session.refresh(new_order)

    # Отправляем обновленное меню с кнопкой отмены
    await callback.message.edit_text(
        f"✅ <b>Заявка успешно оформлена!</b>\n\n"
        f"🚚 {pickup_text}\n\n"
        f"Спасибо за выбор нашего сервиса!",
        parse_mode="HTML"
    )
    await callback.message.answer(
        "🏠 Вернул вас в главное меню.",
        reply_markup=await main_menu_keyboard(callback.from_user.id)  # Принудительное обновление
    )

    # Уведомление администраторам
    for admin_id_str in ADMIN_IDS:
        try:
            admin_id = int(admin_id_str)
        except ValueError:
            continue

        try:
            await callback.bot.send_message(
                admin_id,
                text=(
                    f"Новая заявка #{new_order.id}\n"
                    f"От: @{callback.from_user.username}\n"
                    f"Пользователь выбрал: {delivery_day}\n"
                    f"Оформлена в {now.strftime('%Y-%m-%d %H:%M')} по Москве\n"
                    f"Статус: Новая (От пользователя)\n\n"
                    f"{pickup_text}"
                ),
                reply_markup=admin_orders_button()
            )
        except Exception as e:
            print(f"Ошибка уведомления админа {admin_id}: {e}")

    await state.clear()


@router.message(lambda message: "Написать напрямую" in message.text)
async def direct_message_start(message: types.Message, state: FSMContext):
    builder = InlineKeyboardBuilder()
    builder.button(text="Отмена", callback_data="cancel_direct_message")
    builder.adjust(1)
    
    await message.answer(
        "Введите текст сообщения, и мы перешлём его администратору.\n"
        "После отправки вы получите уведомление, что админ получил сообщение.",
        reply_markup=builder.as_markup()
    )
    await state.set_state(DirectMessageStates.waiting_for_text)


@router.callback_query(F.data == "cancel_direct_message")
async def cancel_direct_message(callback: types.CallbackQuery, state: FSMContext):
    builder = InlineKeyboardBuilder()
    builder.adjust(1)
    
    await callback.message.edit_text("Отправка сообщения отменена.", reply_markup=builder.as_markup())
    await state.clear()


@router.message(DirectMessageStates.waiting_for_text)
async def direct_message_finish(message: types.Message, state: FSMContext):
    user_text = message.text
    user_id = message.from_user.id
    username = message.from_user.username or "NoUsername"

    async with async_sessionmaker() as session:
        result = await session.execute(select(User).where(User.telegram_id == user_id))
        user_obj = result.scalar_one_or_none()

    name = user_obj.name if user_obj else "Неизвестный"
    phone = user_obj.phone if user_obj and user_obj.phone else "Не указан"

    for admin_id_str in ADMIN_IDS:
        try:
            admin_id = int(admin_id_str)
        except ValueError:
            continue

        try:
            await message.bot.send_message(
                admin_id,
                text=(
                    "📩 <b>Новое сообщение от пользователя</b>\n\n"
                    f"👤 <b>Имя:</b> {name}\n"
                    f"🆔 <b>ID:</b> {user_id}\n"
                    f"🔗 <b>Тег:</b> @{username}\n"
                    f"📞 <b>Телефон:</b> {phone}\n\n"
                    f"✉️ <b>Текст сообщения:</b>\n{user_text}"
                ),
                parse_mode="HTML"
            )
        except Exception as e:
            print(f"[direct_message_finish] Ошибка уведомления админа {admin_id}: {e}")

    await message.answer(
        "✅ <b>Ваше сообщение отправлено администратору.</b>\n"
        "Ожидайте, с вами свяжутся в ближайшее время!",
        reply_markup=await main_menu_keyboard(user_id),  # Используем обновленную функцию
        parse_mode="HTML"
    )
    await state.clear()


@router.message(lambda message: "Изменить данные" in message.text)
async def edit_data_menu(message: types.Message, state: FSMContext):
    kb = ReplyKeyboardBuilder()
    kb.button(text="📞 Изменить телефон")
    kb.button(text="🏠 Изменить адрес")
    kb.button(text="👤 Изменить имя")
    kb.button(text="🏢 Изменить организацию")
    kb.button(text="↩️ Назад")
    kb.adjust(1)
    await message.answer(
        "🔄 Выберите, что хотите изменить:",
        reply_markup=kb.as_markup(resize_keyboard=True),
        parse_mode="HTML"
    )
    await state.set_state(EditDataStates.choose_field)


@router.message(EditDataStates.choose_field, F.text == "📞 Изменить телефон")
async def edit_phone_start(message: types.Message, state: FSMContext):
    await message.answer("Введите новый номер телефона:")
    await state.set_state(EditDataStates.waiting_for_new_phone)


@router.message(EditDataStates.waiting_for_new_phone)
async def edit_phone_finish(message: types.Message, state: FSMContext):
    new_phone = message.text
    async with async_sessionmaker() as session:
        user_in_db = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = user_in_db.scalar_one_or_none()
        if user:
            user.phone = new_phone
            await session.commit()

    await message.answer(f"📞 Телефон изменён на: {new_phone}", reply_markup=await main_menu_keyboard(message.from_user.id))
    await state.clear()


@router.message(EditDataStates.choose_field, F.text == "🏠 Изменить адрес")
async def edit_address_start(message: types.Message, state: FSMContext):
    await message.answer("Введите новый адрес:")
    await state.set_state(EditDataStates.waiting_for_new_address)


@router.message(EditDataStates.waiting_for_new_address)
async def edit_address_finish(message: types.Message, state: FSMContext):
    new_address = message.text
    async with async_sessionmaker() as session:
        user_in_db = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = user_in_db.scalar_one_or_none()
        if user:
            user.address = new_address
            await session.commit()

    await message.answer(f"🏠 Адрес изменён на: {new_address}", reply_markup=await main_menu_keyboard(message.from_user.id))
    await state.clear()


@router.message(EditDataStates.choose_field, F.text == "👤 Изменить имя")
async def edit_name_start(message: types.Message, state: FSMContext):
    await message.answer("Введите новое имя:")
    await state.set_state(EditDataStates.waiting_for_new_name)


@router.message(EditDataStates.waiting_for_new_name)
async def edit_name_finish(message: types.Message, state: FSMContext):
    new_name = message.text
    async with async_sessionmaker() as session:
        user_in_db = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = user_in_db.scalar_one_or_none()
        if user:
            user.name = new_name
            await session.commit()

    await message.answer(f"👤 Имя изменено на: {new_name}", reply_markup=await main_menu_keyboard(message.from_user.id))
    await state.clear()


@router.message(EditDataStates.choose_field, F.text == "🏢 Изменить организацию")
async def edit_organization_start(message: types.Message, state: FSMContext):
    await message.answer("Введите новую организацию:")
    await state.set_state(EditDataStates.waiting_for_new_organization)


@router.message(EditDataStates.waiting_for_new_organization)
async def edit_organization_finish(message: types.Message, state: FSMContext):
    new_organization = message.text
    async with async_sessionmaker() as session:
        user_in_db = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = user_in_db.scalar_one_or_none()
        if user:
            user.organization = new_organization
            await session.commit()

    await message.answer(f"🏢 Организация изменена на: {new_organization}", reply_markup=await main_menu_keyboard(message.from_user.id))
    await state.clear()


@router.message(EditDataStates.choose_field, F.text == "↩️ Назад")
async def edit_data_back(message: types.Message, state: FSMContext):
    await message.answer("🏠 Возвращаюсь в главное меню.", reply_markup=await main_menu_keyboard(message.from_user.id))
    await state.clear()


@router.message(lambda message: "Отменить заказ" in message.text)
async def cancel_order_by_user(message: types.Message):
    async with async_sessionmaker() as session:
        try:
            # Ищем активный заказ пользователя
            active_order = await session.execute(
                select(Order)
                .join(User)
                .where(
                    User.telegram_id == message.from_user.id,
                    Order.status != "Исполнено"
                )
            )
            active_order = active_order.scalar_one_or_none()

            if not active_order:
                await message.answer("❌ У вас нет активных заказов для отмены.")
                return

            # Получаем данные пользователя
            user = await session.execute(
                select(User).where(User.telegram_id == message.from_user.id)
            )
            user = user.scalar_one_or_none()

            if not user:
                await message.answer("❌ Ошибка: данные пользователя не найдены")
                return

            # Удаляем активный заказ
            await session.delete(active_order)
            await session.commit()

            # Уведомление пользователя
            await message.answer(
                "✅ Ваш заказ успешно отменён!",
                reply_markup=await main_menu_keyboard(message.from_user.id)
            )

            # Уведомление администраторам
            for admin_id in ADMIN_IDS:
                try:
                    await message.bot.send_message(
                        admin_id,
                        f"⚠️ Пользователь @{message.from_user.username} отменил заказ.\n"
                        f"👤 Имя: {user.name}\n"
                        f"📞 Телефон: {user.phone}\n"
                        f"🕒 Время: {datetime.now(MOSCOW_TZ).strftime('%d.%m.%Y %H:%M')}"
                    )
                except Exception as e:
                    logging.error(f"Ошибка уведомления админа: {e}")

        except Exception as e:
            logging.error(f"Ошибка отмены заказа: {e}")
            await message.answer("❌ Произошла ошибка при отмене заказа")