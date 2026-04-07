# handlers/top.py

from telegram import Update
from telegram.ext import ContextTypes
from services.user_service import get_top_users, get_user_rank, get_weekly_top_users

MEDALS = ['🥇', '🥈', '🥉']


def get_level(points: int) -> str:
    if points >= 500:
        return "🌳 Эко-мастер"
    elif points >= 200:
        return "🌿 Эко-активист"
    elif points >= 50:
        return "🌱 Эко-новичок"
    else:
        return "🌰 Начинающий"


def get_progress_bar(points: int) -> str:
    thresholds = [0, 50, 200, 500]
    for i in range(len(thresholds) - 1):
        if points < thresholds[i + 1]:
            progress = (points - thresholds[i]) / (thresholds[i + 1] - thresholds[i])
            filled = int(progress * 10)
            return f"{'█' * filled}{'░' * (10 - filled)} {points}/{thresholds[i + 1]}"
    return f"{'█' * 10} {points} 🏆 MAX"


async def top_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    weekly = args and args[0].lower() == "week"
    telegram_id = update.effective_user.id

    if weekly:
        users = get_weekly_top_users(10)
        title = "📅 Топ-10 за эту неделю"
    else:
        users = get_top_users(10)
        title = "🏆 Топ-10 EcoScaner (все время)"

    lines = [f"<b>{title}</b>\n"]

    if not users:
        await update.message.reply_text("📊 Пока нет участников. Будь первым!")
        return

    for i, u in enumerate(users):
        medal = MEDALS[i] if i < 3 else f"{i + 1}."
        name  = u.get("first_name") or "Аноним"
        cnt   = u.get("total_wastes", 0)

        # ✅ DÜZELTME: seviye ve gösterim için total_earned_points kullan.
        # total_points harcamayla düşer → seviye yanlış hesaplanıyordu.
        pts   = u.get("total_earned_points") or u.get("total_points", 0)
        level = get_level(pts)
        lines.append(f"{medal} {name} — <b>{pts}</b> балл. ({cnt} бут.) {level}")

    rank_info = get_user_rank(telegram_id, weekly=weekly)
    if rank_info:
        rank = rank_info["rank"]
        cnt  = rank_info["total_wastes"]

        # ✅ DÜZELTME: rank sorgusundan gelen total_points zaten
        # get_user_rank() içinde total_earned_points'ten geliyor.
        pts      = rank_info["total_points"]
        level    = get_level(pts)
        progress = get_progress_bar(pts)

        lines.append(f"\n──────────────")
        lines.append(f"📍 <b>Твоё место: {rank}-е</b>")
        lines.append(f"💎 {pts} балл. ({cnt} бут.) {level}")
        lines.append(f"📈 {progress}")
    else:
        lines.append(f"\n──────────────")
        lines.append(f"📍 Ты ещё не в рейтинге. Отправь фото мусора! ♻️")

    lines.append(f"\n💡 /top week — рейтинг за неделю")
    lines.append(f"💡 /top — рейтинг за всё время")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")