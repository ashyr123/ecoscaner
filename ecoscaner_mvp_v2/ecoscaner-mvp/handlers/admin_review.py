# handlers/admin_review.py
# FIX: callback_data 64-byte sınırı aşımı düzeltildi.
#      ph (phash) ve fi (file_id) artık callback içinde taşınmıyor;
#      handle_review_callback içinde review_queue tablosundan çekiliyor.

import hashlib
import json
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config.settings import ADMIN_GROUP_ID
from database.db import get_connection
from services.waste_service import (
    WasteRecord,
    add_waste,
    get_points_for_category,
    build_fingerprint_from_ai,
)
from services.user_service import get_user

logger = logging.getLogger(__name__)

_CAT_EMOJI = {"plastic": "🧴", "metal": "🥫", "glass": "🍶", "cardboard": "📦"}
_CAT_RU = {"plastic": "Пластик", "metal": "Металл", "glass": "Стекло", "cardboard": "Картон"}


# ─────────────────────────────────────────────────────────────
# review_queue yardımcıları
# ─────────────────────────────────────────────────────────────

def _get_review_row(review_id: int) -> dict | None:
    """review_queue tablosundan satırı döner."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM review_queue WHERE id = ?",
            (review_id,),
        ).fetchone()
        return dict(row) if row else None


def _mark_resolved(review_id: int) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE review_queue SET resolved = 1 WHERE id = ?",
            (review_id,),
        )
        conn.commit()


# ─────────────────────────────────────────────────────────────
# Admin gruba bildirim gönder
# ─────────────────────────────────────────────────────────────

async def notify_admins_review(
    context,
    review_id: int,
    telegram_id: int,
    result_a: dict,
    result_b: dict,
    phash: str,
    file_id: str = "",
) -> None:
    if not ADMIN_GROUP_ID:
        logger.warning("ADMIN_GROUP_ID tanımlı değil — review bildirimi gönderilemedi")
        return

    user = get_user(telegram_id)
    username = user.get("username", "") if user else ""
    fullname = user.get("first_name", "?") if user else "?"

    cat_a = result_a.get("category", "?")
    cat_b = result_b.get("category", "?")
    brand = result_a.get("brand") or result_b.get("brand") or "UNKNOWN"
    conf_a = result_a.get("confidence", 0)
    conf_b = result_b.get("confidence", 0)

    user_line = fullname
    if username:
        user_line += " @" + username
    user_line += " (<code>" + str(telegram_id) + "</code>)"

    caption = (
        "🔎 <b>İnceleme #" + str(review_id) + "</b>\n\n"
        "👤 " + user_line + "\n"
        "🤖 GPT-4o-mini: <b>" + cat_a + "</b> (" + str(conf_a) + "%)\n"
        "🤖 Gemini: <b>" + cat_b + "</b> (" + str(conf_b) + "%)\n"
        "🏷 Marka: " + brand + "\n\n"
        "Hangi kategori doğru? 👇"
    )

    # ─── FIX: callback_data artık YALNIZCA review_id + action taşıyor ───
    # ph ve fi kaldırıldı; handle_review_callback DB'den çekecek.
    # Maksimum callback boyutu: {"a":"ra","r":9999999,"c":"cardboard"} = ~42 byte ✅

    def _cb(action: str, **kw) -> str:
        payload = {"a": action, "r": review_id, **kw}
        data = json.dumps(payload, separators=(",", ":"))
        assert len(data.encode()) <= 64, f"callback_data {len(data.encode())} byte — sınır aşıldı!"
        return data

    keyboard = [
        [
            InlineKeyboardButton(
                _CAT_EMOJI.get(cat, "♻️") + " " + _CAT_RU.get(cat, cat),
                callback_data=_cb("ra", c=cat),   # ← sadece kategori
            )
            for cat in ("plastic", "metal", "glass", "cardboard")
        ],
        [
            InlineKeyboardButton(
                "❌ Отклонить",
                callback_data=_cb("rr"),
            )
        ],
    ]
    markup = InlineKeyboardMarkup(keyboard)

    try:
        if file_id:
            await context.bot.send_photo(
                chat_id=ADMIN_GROUP_ID,
                photo=file_id,
                caption=caption,
                parse_mode="HTML",
                reply_markup=markup,
            )
        else:
            await context.bot.send_message(
                chat_id=ADMIN_GROUP_ID,
                text=caption,
                parse_mode="HTML",
                reply_markup=markup,
            )
    except Exception as e:
        logger.error("Grup bildirimi gönderilemedi: %s", e)


# ─────────────────────────────────────────────────────────────
# Callback handler
# ─────────────────────────────────────────────────────────────

async def handle_review_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    try:
        data = json.loads(query.data)
    except Exception:
        await query.edit_message_text("❌ Geçersiz callback verisi.")
        return

    action = data.get("a")
    review_id = data.get("r")
    admin = update.effective_user
    admin_name = admin.full_name if admin else "Admin"

    # ─── FIX: ph, fi ve AI sonuçları DB'den çekiliyor ───────
    row = _get_review_row(review_id)
    if not row:
        await query.edit_message_text("❌ Review bulunamadı (zaten çözüldü?).")
        return

    user_id = row["telegram_id"]
    phash = row.get("phash", "")
    file_id = row.get("file_id", "")
    has_photo = bool(file_id)

    try:
        result_a = json.loads(row.get("result_a") or "{}")
        result_b = json.loads(row.get("result_b") or "{}")
    except Exception:
        result_a, result_b = {}, {}

    # ─── Reddet ─────────────────────────────────────────────
    if action == "rr":
        _mark_resolved(review_id)
        edited_text = "❌ #" + str(review_id) + " — <b>" + admin_name + "</b> tarafından reddedildi."
        if has_photo:
            await query.edit_message_caption(caption=edited_text, parse_mode="HTML")
        else:
            await query.edit_message_text(edited_text, parse_mode="HTML")
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text="❌ Фото проверено — не принято.\nСделай новый снимок и попробуй снова! 📸",
            )
        except Exception as e:
            logger.warning("Kullanıcıya red bildirimi gönderilemedi: %s", e)
        return

    # ─── Kabul et ───────────────────────────────────────────
    if action == "ra":
        category = data.get("c", "plastic")

        # Kararı veren AI'ın sonucunu öncelikli kullan
        a_cat = result_a.get("category", "")
        chosen = result_a if a_cat == category else result_b

        brand = chosen.get("brand") or result_a.get("brand") or "UNKNOWN"
        is_empty = bool(chosen.get("is_empty", True))
        is_damaged = bool(chosen.get("is_damaged", False))
        volume = chosen.get("volume", "UNKNOWN")
        color = chosen.get("color", "UNKNOWN")

        base_points = get_points_for_category(category, is_empty)
        fingerprint = build_fingerprint_from_ai(brand, volume, color)
        fake_hash = hashlib.sha256(
            ("review_" + str(review_id) + "_" + str(user_id)).encode()
        ).hexdigest()

        rec = WasteRecord(
            telegram_id=user_id,
            image_hash=fake_hash,
            phash=phash,
            file_id=file_id,
            points=base_points,
            brand=brand,
            fingerprint=fingerprint,
            category=category,
            is_empty=is_empty,
            is_damaged=is_damaged,
        )
        add_waste(rec)
        _mark_resolved(review_id)

        edited_text = (
            "✅ #" + str(review_id)
            + " — <b>" + admin_name + "</b> onayladı: <b>"
            + _CAT_RU.get(category, category) + "</b> (+" + str(base_points) + " puan)"
        )
        if has_photo:
            await query.edit_message_caption(caption=edited_text, parse_mode="HTML")
        else:
            await query.edit_message_text(edited_text, parse_mode="HTML")

        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    "✅ Фото проверено и принято!\n\n"
                    f"{_CAT_EMOJI.get(category, '♻️')} {_CAT_RU.get(category, category)} "
                    f"— <b>+{base_points}</b> баллов\n"
                    "Спасибо за участие! 🌱"
                ),
                parse_mode="HTML",
            )
        except Exception as e:
            logger.warning("Kullanıcıya onay bildirimi gönderilemedi: %s", e)