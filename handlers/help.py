from telegram import Update
from telegram.ext import ContextTypes


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        '<b>♻️ EcoScaner — Помощь</b>\n\n'
        '<b>Как пользоваться:</b>\n'
        '1. Сфотографируй пластиковую бутылку\n'
        '2. Отправь фото в бот\n'
        '3. Получи +5 баллов\n\n'
        '<b>Правила:</b>\n'
        '• Максимум 10 фото в день\n'
        '• Одно и то же фото принимается только 1 раз\n\n'
        '<b>Баллы и уровни:</b>\n'
        '• Баллы на счету можно тратить в магазине (/store)\n'
        '• Уровень растёт по общему количеству заработанных баллов и никогда не уменьшается\n\n'
        '<b>Команды:</b>\n'
        '/start — начало\n'
        '/profile — мой профиль\n'
        '/top — таблица лидеров\n'
        '/store — магазин (потратить баллы)\n'
        '/lottery — розыгрыш (купить билеты)\n'
        '/help — помощь'
    )
    await update.message.reply_text(text, parse_mode='HTML')
