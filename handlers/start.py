# handlers/start.py

from telegram import Update
from telegram.ext import ContextTypes
from services.user_service import get_or_create_user


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    get_or_create_user(user.id, user.username, user.first_name)
    text = (
        f'<b>♻️ Добро пожаловать в EcoScaner, {user.first_name}!</b>\n\n'
        'Отправляй фото перерабатываемых отходов и получай баллы!\n\n'
        '<b>Как это работает:</b>\n'
        '1. Сфотографируй упаковку крупным планом\n'
        '2. Отправь фото в этот бот\n'
        '3. ИИ определит тип и начислит баллы\n\n'
        '<b>💎 Баллы по категориям:</b>\n'
        '🧴 Пластик — 5 баллов (пустой)\n'
        '🥫 Металл — 6 баллов (пустой)\n'
        '🍶 Стекло — 8 баллов (пустой)\n'
        '📦 Картон — 3 балла (пустой)\n'
        '<i>Полная тара даёт половину баллов.</i>\n\n'
        '🏅 Уровень растёт по общему количеству заработанных баллов.\n'
        '🛍 Трать баллы в /store — значки, статусы, билеты на розыгрыш.\n\n'
        '<b>Команды:</b>\n'
        '/profile — мой профиль\n'
        '/top — топ-10 участников\n'
        '/store — магазин наград\n'
        '/help — помощь\n\n'
        'Начинай прямо сейчас! 🚀'
    )
    await update.message.reply_text(text, parse_mode='HTML')