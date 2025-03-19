# anti_spam.py
import time
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.types import Message, TelegramObject

class AntiSpamMiddleware(BaseMiddleware):
    def __init__(self, time_window: float = 5, max_messages: int = 3):
        self.time_window = time_window
        self.max_messages = max_messages
        self.users = {}

    async def __call__(self, handler, event: TelegramObject, data: dict):
        if isinstance(event, Message) and event.from_user:
            user_id = event.from_user.id
            now = time.time()
            
            # Обнуляем счетчик если временное окно истекло
            if user_id in self.users and now - self.users[user_id]["last_time"] > self.time_window:
                del self.users[user_id]

            if user_id not in self.users:
                self.users[user_id] = {
                    "count": 1,
                    "last_time": now,
                    "last_warning": 0
                }
            else:
                self.users[user_id]["count"] += 1

            # Блокируем если превышен лимит
            if self.users[user_id]["count"] > self.max_messages:
                if now - self.users[user_id]["last_warning"] > self.time_window:
                    try:
                        await event.answer("❗️ Пожалуйста, не спамьте!")
                        self.users[user_id]["last_warning"] = now
                    except Exception:
                        pass
                return
            
            self.users[user_id]["last_time"] = now
            
        return await handler(event, data)