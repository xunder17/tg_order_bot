import asyncio

import logging

from datetime import datetime
from main import create_dispatcher, setup_logger
from db import init_db
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from handlers.admin import cleanup_old_orders

from config import CLEANUP_HOUR, CLEANUP_MINUTE, CLEANUP_TIMEZONE


async def main() -> None:
    """
    Главная точка входа в приложение:
    1. Настраивает логирование.
    2. Инициализирует базу данных.
    3. Запускает планировщик задач (чистка старых заявок).
    4. Запускает бота в режиме long polling.
    """
    setup_logger()
    dp, bot = create_dispatcher()

    await bot.delete_webhook(drop_pending_updates=True)

    try:
        await init_db()
        logging.info("Database initialized successfully.")
    except Exception as e:
        logging.error(f"Failed to initialize database: {e}")
        return

    scheduler = AsyncIOScheduler(timezone=CLEANUP_TIMEZONE)
    scheduler.add_job(
        cleanup_old_orders,
        "cron",
        hour=CLEANUP_HOUR,
        minute=CLEANUP_MINUTE,
        second=0,
        timezone=CLEANUP_TIMEZONE
    )

    try:
        scheduler.start()
        logging.info(
            f"Scheduler started with cleanup at {CLEANUP_HOUR:02d}:{CLEANUP_MINUTE:02d} "
            f"({CLEANUP_TIMEZONE}) daily."
        )

        await dp.start_polling(bot)

    except Exception as e:
        logging.error(f"Error in bot polling or scheduler: {e}")

    finally:
        scheduler.shutdown()
        logging.info("Scheduler shut down.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Bot stopped by user.")
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
