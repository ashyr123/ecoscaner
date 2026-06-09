# handlers/store.py

from telegram import Update
from telegram.ext import ContextTypes

from services.user_service import get_or_create_user, get_balance
from services.store_service import get_active_items, buy_item


def _sorted_items(items: list[dict]) -> list[dict]:
    return sorted(items, key=lambda x: (x.get("price", 0), x.get("id", 0)))


# ─────────────────────────────────────────────────────────────
# /store
# ─────────────────────────────────────────────────────────────

async def store_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    get_or_create_user(user.id, user.username or "", user.first_name or "")

    balance, _ = get_balance(user.id)
    items = _sorted_items(get_active_items())

    if not items:
        await update.message.reply_text(
            "🛍 <b>Магазин пока пуст</b>\n\nСкоро здесь появятся награды!",
            parse_mode="HTML",
        )
        return

    lines = [
        "<b>🛍 Магазин наград</b>",
        "",
        f"💎 Твой баланс: <b>{balance}</b> баллов",
        "",
        "Купи награду командой <code>/buy ID</code>",
        "Пример: <code>/buy 3</code>",
    ]

    for item in items:
        can_buy = "✅" if balance >= item["price"] else "🔒"
        stock_label = (
            f"Осталось: {item['stock']} шт."
            if item.get("stock", -1) != -1
            else "Без ограничений"
        )

        lines.extend([
            "",
            f"{can_buy} <b>#{item['id']} — {item.get('name', '?')}</b>",
            f"💰 Цена: <b>{item.get('price', 0)}</b> баллов",
            f"📦 {stock_label}",
            item.get("description") or "",
        ])

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


# ─────────────────────────────────────────────────────────────
# /buy <id>
# ─────────────────────────────────────────────────────────────

async def buy_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    get_or_create_user(user.id, user.username or "", user.first_name or "")

    if not context.args:
        await update.message.reply_text(
            "🛒 Использование: <code>/buy ID</code>\n"
            "Пример: <code>/buy 3</code>\n\n"
            "Сначала открой <code>/store</code> и выбери нужный ID.",
            parse_mode="HTML",
        )
        return

    try:
        item_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text(
            "❌ ID должно быть числом.\n"
            "Пример: <code>/buy 3</code>",
            parse_mode="HTML",
        )
        return

    before_balance, _ = get_balance(user.id)
    ok, msg = buy_item(user.id, item_id)
    after_balance, _ = get_balance(user.id)

    if ok:
        text = (
            f"{msg}\n\n"
            f"💎 Остаток на счёте: <b>{after_balance}</b> баллов\n"
            f"👤 Проверь награду в команде <code>/profile</code>"
        )
    else:
        text = (
            f"{msg}\n\n"
            f"💎 Текущий баланс: <b>{before_balance}</b> баллов\n"
            f"🛍 Посмотреть товары: <code>/store</code>"
        )

    await update.message.reply_text(text, parse_mode="HTML")