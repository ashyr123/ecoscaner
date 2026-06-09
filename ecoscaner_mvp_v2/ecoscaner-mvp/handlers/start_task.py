from telegram import Update
from telegram.ext import ContextTypes
from services.task_service import generate_token


async def handle_start_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    token = generate_token(user_id)
    await update.message.reply_text(
        f"📋 <b>Задание начато!</b>\n\n"
        f"✏️ Напиши этот код на бумаге: <b>{token}</b>\n"
        f"📸 Положи бумагу рядом с мусором и сфотографируй!\n\n"
        f"⏳ Код действителен 5 минут.",
        parse_mode="HTML"
    )