import time
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.types import Message, TelegramObject

class AntiSpamMiddleware(BaseMiddleware):
    """
    Middleware, которое отслеживает частоту сообщений от пользователя.
    Если за заданное окно времени (time_window) пользователь отправляет более
    max_messages сообщений, ему отправляется предупреждение, а сообщение не передаётся дальше.
    """
    def __init__(self, time_window: float = 5, max_messages: int = 3):
        self.time_window = time_window
        self.max_messages = max_messages
        self.users = {}

    async def __call__(self, handler, event: TelegramObject, data: dict):
        if isinstance(event, Message) and event.from_user:
            user_id = event.from_user.id
            now = time.time()
            user_data = self.users.get(user_id, {"timestamps": [], "last_warning": 0})
            timestamps = [ts for ts in user_data["timestamps"] if now - ts < self.time_window]
            timestamps.append(now)
            user_data["timestamps"] = timestamps
            self.users[user_id] = user_data

            if len(timestamps) > self.max_messages:
                if now - user_data["last_warning"] > self.time_window:
                    try:
                        await event.answer("❗️ Пожалуйста, не спамьте!")
                    except Exception:
                        pass
                    user_data["last_warning"] = now
                return
        return await handler(event, data)
