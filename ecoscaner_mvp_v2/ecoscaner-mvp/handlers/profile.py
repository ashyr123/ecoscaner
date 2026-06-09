from telegram import Update
from telegram.ext import ContextTypes

from services.user_service import get_or_create_user, get_user, get_balance
from services.store_service import get_user_purchases


def get_level(total_earned_points: int) -> str:
    if total_earned_points >= 500:
        return "🌳 Эко-мастер"
    elif total_earned_points >= 200:
        return "🌿 Эко-активист"
    elif total_earned_points >= 50:
        return "🌱 Эко-новичок"
    else:
        return "🌰 Начинающий"


async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    get_or_create_user(user.id, user.username, user.first_name)

    p = get_user(user.id)
    name = p.get("first_name") or "Пользователь"
    wastes = p.get("total_wastes", 0)

    balance, total_earned = get_balance(user.id)
    level = get_level(total_earned)
    purchases = get_user_purchases(user.id)

    text = (
        "<b>👤 Твой профиль</b>\n\n"
        f"Имя: {name}\n"
        f"Уровень: {level}\n\n"
        f"💎 Баллы на счету: <b>{balance}</b>\n"
        f"📈 Всего заработано: <b>{total_earned}</b>\n"
        f"♻️ Бутылок сдано: <b>{wastes}</b>\n"
    )

    if purchases:
        text += "\n<b>🎁 Твои награды:</b>\n"

        seen = set()
        for item in purchases:
            key = item["item_id"]
            if key in seen:
                continue
            seen.add(key)
            text += f"• {item['name']}\n"
    else:
        text += "\n<i>Пока нет наград. Загляни в /store</i>\n"

    text += "\nПродолжай — больше бутылок, выше уровень и больше возможностей в магазине! 🚀"

    await update.message.reply_text(text, parse_mode="HTML")