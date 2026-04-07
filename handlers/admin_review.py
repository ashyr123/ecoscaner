# handlers/admin_review.py
# Review queue'daki fotoğrafları admin'e Telegram üzerinden gönderir.
# Admin ✅ veya ❌ butonuna basınca bot otomatik karar verir.

import json
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler

from config.settings import ADMIN_TELEGRAM_IDS
from database.db import get_connection
from services.waste_service import (
    WasteRecord,
    add_waste,
    get_points_for_category,
    build_fingerprint_from_ai,
)
from services.user_service import get_user

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Review kuyruğuna yeni öğe eklenince admin'e bildirim gönder
# ─────────────────────────────────────────────────────────────

async def notify_admins_review(
    context,
    review_id: int,
    telegram_id: int,
    result_a: dict,
    result_b: dict,
    phash: str,
) -> None:
    """
    Review queue'ya yeni fotoğraf düştüğünde tüm admin'lere bildirim gönderir.
    Inline butonlar: ✅ Kabul (hangi kategoriyle?) | ❌ Reddet
    """
    if not ADMIN_TELEGRAM_IDS:
        logger.warning("ADMIN_TELEGRAM_IDS boş — review bildirimi gönderilemedi")
        return

    user = get_user(telegram_id)
    user_name = user.get("first_name", "?") if user else "?"

    cat_a = result_a.get("category", "?")
    cat_b = result_b.get("category", "?")
    brand = result_a.get("brand") or result_b.get("brand") or "UNKNOWN"
    conf_a = result_a.get("confidence", 0)
    conf_b = result_b.get("confidence", 0)

    text = (
        f"🔎 <b>Yeni inceleme isteği #{review_id}</b>\n\n"
        f"👤 Kullanıcı: {user_name} (<code>{telegram_id}</code>)\n"
        f"🤖 GPT-4o-mini: <b>{cat_a}</b> (güven: {conf_a}%)\n"
        f"🤖 Gemini: <b>{cat_b}</b> (güven: {conf_b}%)\n"
        f"🏷 Marka: {brand}\n\n"
        "Hangi kategori doğru?"
    )

    # Her kategori için buton
    categories = [
        ("🧴 Plastik", "plastic"),
        ("🥫 Metal",   "metal"),
        ("🍶 Стекло",  "glass"),
        ("📦 Karton",  "cardboard"),
    ]

    keyboard = [
        [
            InlineKeyboardButton(
                label,
                callback_data=json.dumps({
                    "action":  "review_accept",
                    "rid":     review_id,
                    "uid":     telegram_id,
                    "cat":     cat,
                    "brand":   brand,
                    "empty":   result_a.get("is_empty", True),
                    "damaged": result_a.get("is_damaged", False),
                    "vol":     result_a.get("volume", "UNKNOWN"),
                    "color":   result_a.get("color", "UNKNOWN"),
                    "phash":   phash,
                })
            )
            for label, cat in categories
        ],
        [
            InlineKeyboardButton(
                "❌ Reddet",
                callback_data=json.dumps({
                    "action": "review_reject",
                    "rid":    review_id,
                    "uid":    telegram_id,
                })
            )
        ]
    ]

    markup = InlineKeyboardMarkup(keyboard)

    for admin_id in ADMIN_TELEGRAM_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=text,
                parse_mode="HTML",
                reply_markup=markup,
            )
        except Exception as e:
            logger.error("Admin bildirimi gönderilemedi admin_id=%d: %s", admin_id, e)


# ─────────────────────────────────────────────────────────────
# Callback handler — admin butona basınca
# ─────────────────────────────────────────────────────────────

async def handle_review_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    try:
        data = json.loads(query.data)
    except Exception:
        await query.edit_message_text("❌ Geçersiz callback verisi.")
        return

    action    = data.get("action")
    review_id = data.get("rid")
    user_id   = data.get("uid")

    if action == "review_reject":
        _mark_resolved(review_id)
        await query.edit_message_text(
            f"❌ #{review_id} reddedildi. Kullanıcıya bildirim gönderildi."
        )
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text="❌ İnceleme sonucu: fotoğrafın kabul edilmedi.\nBaşka bir fotoğraf gönderebilirsin!"
            )
        except Exception as e:
            logger.warning("Kullanıcıya red bildirimi gönderilemedi: %s", e)
        return

    if action == "review_accept":
        category = data.get("cat", "plastic")
        brand    = data.get("brand", "UNKNOWN")
        is_empty = data.get("empty", True)
        is_damaged = data.get("damaged", False)
        volume   = data.get("vol", "UNKNOWN")
        color    = data.get("color", "UNKNOWN")
        phash    = data.get("phash", "")

        base_points = get_points_for_category(category, is_empty)
        fingerprint = build_fingerprint_from_ai(brand, volume, color)

        # Waste kaydı oluştur — image_hash review_id'den türetilir (unique)
        import hashlib
        fake_hash = hashlib.sha256(f"review_{review_id}_{user_id}".encode()).hexdigest()

        rec = WasteRecord(
            telegram_id=user_id,
            image_hash=fake_hash,
            phash=phash,
            file_id="",
            points=base_points,
            brand=brand,
            fingerprint=fingerprint,
            category=category,
            is_empty=is_empty,
            is_damaged=is_damaged,
            raw_volume=volume,
            raw_color=color,
            fraud_score=0.5,
            event_proof="admin_approved",
        )
        add_waste(rec)
        _mark_resolved(review_id)

        cat_emoji = {"plastic": "🧴", "metal": "🥫", "glass": "🍶", "cardboard": "📦"}.get(category, "♻️")

        await query.edit_message_text(
            f"✅ #{review_id} kabul edildi — {cat_emoji} {category}, +{base_points} puan"
        )
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    f"✅ İnceleme sonucu: fotoğrafın kabul edildi!\n"
                    f"{cat_emoji} Kategori: {category}\n"
                    f"💎 +{base_points} puan hesabına eklendi!"
                ),
                parse_mode="HTML",
            )
        except Exception as e:
            logger.warning("Kullanıcıya kabul bildirimi gönderilemedi: %s", e)


def _mark_resolved(review_id: int) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE review_queue SET resolved = 1 WHERE id = ?",
            (review_id,),
        )
        conn.commit()


# ─────────────────────────────────────────────────────────────
# Handler kaydı — main.py veya run.py'de kullan
# ─────────────────────────────────────────────────────────────

def get_review_handler() -> CallbackQueryHandler:
    """
    main.py'de şöyle ekle:
        from handlers.admin_review import get_review_handler
        app.add_handler(get_review_handler())
    """
    return CallbackQueryHandler(
        handle_review_callback,
        pattern=r'^\{"action": "review_'
    )