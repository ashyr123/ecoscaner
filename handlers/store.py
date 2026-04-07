# handlers/store.py

from telegram import Update
from telegram.ext import ContextTypes

from services.user_service import get_or_create_user, get_balance
from services.store_service import get_active_items, buy_item


# ─────────────────────────────────────────────────────────────
# /store
# ─────────────────────────────────────────────────────────────

async def store_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    get_or_create_user(user.id, user.username or "", user.first_name or "")

    balance, _ = get_balance(user.id)
    items = get_active_items()

    if not items:
        await update.message.reply_text(
            "🛍 Магазин пока пуст. Скоро здесь появятся награды!",
            parse_mode="HTML",
        )
        return

    lines = [
        "<b>🛍 Магазин наград</b>\n",
        f"💎 Твой баланс: <b>{balance}</b> баллов\n",
        "Купи награду командой <code>/buy ID</code>\n",
    ]

    for item in items:
        stock_label = (
            f"Осталось: {item['stock']} шт." if item["stock"] != -1
            else "Без ограничений"
        )
        lines.append(
            f"\n<b>#{item['id']} — {item['name']}</b>\n"
            f"💰 Цена: <b>{item['price']}</b> баллов\n"
            f"📦 {stock_label}\n"
            f"{item['description'] or ''}"
        )

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


# ─────────────────────────────────────────────────────────────
# /buy <id>
# ─────────────────────────────────────────────────────────────

async def buy_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    get_or_create_user(user.id, user.username or "", user.first_name or "")

    if not context.args:
        await update.message.reply_text(
            "Использование: <code>/buy ID</code>\nПример: <code>/buy 1</code>",
            parse_mode="HTML",
        )
        return

    try:
        item_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text(
            "❌ ID должно быть числом. Пример: <code>/buy 1</code>",
            parse_mode="HTML",
        )
        return

    ok, msg = buy_item(user.id, item_id)
    await update.message.reply_text(msg, parse_mode="HTML")