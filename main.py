import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.bot import DefaultBotProperties

from config import BOT_TOKEN, DEBUG

from handlers import user_registration, order, admin
from handlers.fallback import fallback_router

from middlewares.inactivity import InactivityMiddleware
from middlewares.anti_spam import AntiSpamMiddleware


def create_dispatcher() -> tuple[Dispatcher, Bot]:
    """
    Создаёт диспетчер и бот для работы с Aiogram.
    Возвращает кортеж (dp, bot).
    """
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode='HTML'))
    dp = Dispatcher(storage=MemoryStorage())

    dp.update.middleware(InactivityMiddleware())
    dp.update.middleware(AntiSpamMiddleware(time_window=5, max_messages=3))

    dp.include_router(user_registration.router)
    dp.include_router(order.router)
    dp.include_router(admin.router)
    dp.include_router(fallback_router)

    return dp, bot


def setup_logger() -> None:
    """
    Настраивает логирование для приложения.
    """
    level = logging.DEBUG if DEBUG else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

