from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.types import Message, TelegramObject
from aiogram.fsm.context import FSMContext

from datetime import datetime, timedelta

from handlers.order import main_menu_keyboard


INACTIVITY_TIMEOUT = timedelta(minutes=10)


class InactivityMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: TelegramObject, data: dict):
        if isinstance(event, Message):
            state: FSMContext = data.get("state")

            if state:
                user_data = await state.get_data()
                last_activity = user_data.get("last_activity")

                if last_activity:
                    last_activity = datetime.fromisoformat(last_activity)

                    if datetime.utcnow() - last_activity > INACTIVITY_TIMEOUT:
                        await state.clear()
                        await event.answer(
                            "⏳ Вы долго не общались с ботом. Возвращаем вас в главное меню!",
                            reply_markup=main_menu_keyboard()
                        )

                await state.update_data(last_activity=datetime.utcnow().isoformat())

        return await handler(event, data)