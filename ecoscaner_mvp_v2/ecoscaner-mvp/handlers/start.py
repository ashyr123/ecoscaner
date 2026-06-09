# handlers/start.py
# FIX 7: WEBAPP_URL artık os.getenv() ile değil, config/settings.py üzerinden geliyor.
#         Bu sayede .env değişikliği tüm codebase'e otomatik yansır.

from telegram import Update, WebAppInfo, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config.settings import WEBAPP_URL        # FIX 7: os.getenv kaldırıldı
from services.user_service import get_or_create_user


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    get_or_create_user(user.id, user.username or "", user.first_name or "")

    text = (
        f'<b>♻️ Добро пожаловать в EcoScaner, {user.first_name}!</b>\n\n'
        'Отправляй фото перерабатываемых отходов и получай баллы!\n\n'
        '<b>Как это работает:</b>\n'
        '1. Напиши /scan — получи одноразовый код\n'
        '2. Запиши код на бумаге\n'
        '3. Сфотографируй бумагу рядом с мусором\n'
        '4. Отправь фото — получи баллы!\n\n'
        '<b>💎 Баллы по категориям:</b>\n'
        '🧴 Пластик — 5 баллов (пустой)\n'
        '🥫 Металл — 6 баллов (пустой)\n'
        '🍶 Стекло — 8 баллов (пустой)\n'
        '📦 Картон — 3 балла (пустой)\n'
        '<i>Полная тара даёт половину баллов.</i>\n\n'
        '🏅 Уровень растёт по общему количеству заработанных баллов.\n'
        '🛍 Трать баллы в /store — значки, статусы, билеты на розыгрыш.\n\n'
        '<b>Команды:</b>\n'
        '/scan — начать задание (получить код)\n'
        '/profile — мой профиль\n'
        '/top — топ-10 участников\n'
        '/store — магазин наград\n'
        '/help — помощь\n\n'
        'Начинай прямо сейчас! 🚀'
    )

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            text="📱 Открыть приложение",
            web_app=WebAppInfo(url=WEBAPP_URL),
        ),
    ]])

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=keyboard,
    )