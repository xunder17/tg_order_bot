import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

ADMIN_IDS = os.getenv("ADMIN_IDS").split(",")

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./database.db")

DEBUG = bool(int(os.getenv("DEBUG", "0")))

CLEANUP_HOUR = int(os.getenv("CLEANUP_HOUR", "0"))

CLEANUP_MINUTE = int(os.getenv("CLEANUP_MINUTE", "0"))

CLEANUP_TIMEZONE = os.getenv("CLEANUP_TIMEZONE", "Europe/Moscow")