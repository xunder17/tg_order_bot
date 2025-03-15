from aiogram import Router, types

fallback_router = Router()


@fallback_router.message()
async def fallback_handler(message: types.Message):
    await message.answer(
        "🙃 Извините, я не понял вашу команду.\nПопробуйте воспользоваться меню или введите /start для начала работы.",
        parse_mode="HTML"
    )