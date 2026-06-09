# handlers/photo.py — EcoScaner Telegram handler
# FIX 4: CATEGORY_DAY_LIMIT artık config/settings.py'den geliyor (hardcoded 2 kaldırıldı).
# FIX 2: _call_gpt, _call_gemini, rate_limiter artık services/ai_service.py'den geliyor.

import asyncio
import hashlib
import logging
import time

from telegram import Update
from telegram.ext import ContextTypes

from config.settings import (
    DAILY_LIMIT,
    ACCOUNT_MIN_AGE_DAYS,
    CATEGORY_DAY_LIMIT,      # FIX 4: artık settings'ten
)
from config.bonus_brands import get_bonus_multiplier

from services.ai_service import call_gpt, call_gemini, rate_limiter   # FIX 2: ai_service'ten
from services.waste_service import (
    add_waste,
    file_id_exists,
    fingerprint_exists,
    get_category_daily_count,
    get_points_for_category,
    get_user_daily_count,
    get_user_phashes,
    photo_hash_exists,
    WasteRecord,
)
from services.fingerprint import (
    ProductAnalyzer,
    build_fingerprint,
    get_perceptual_hash,
    is_visually_duplicate,
    resolve_ai_consensus,
)
from services.fraud_scorer import compute_fraud_score
from services.user_service import get_or_create_user, get_user, get_account_age_days
from services.task_service import get_active_token, consume_token
from database.db import get_connection
from handlers.admin_review import notify_admins_review

logger = logging.getLogger(__name__)

ALLOWED_PACKAGING = {"beverage_container", "food_packaging"}

# ─────────────────────────────────────────────────────────────
# Emoji / metin tabloları
# ─────────────────────────────────────────────────────────────

_EMOJI = {"plastic": "🧴", "cardboard": "📦", "glass": "🍶", "metal": "🥫"}
_CAT_RU = {"plastic": "Пластик", "cardboard": "Картон", "glass": "Стекло", "metal": "Металл"}
_FULLNESS = {
    "plastic": "⚠️ Бутылка кажется полной — опустоши для полных очков!",
    "cardboard": "⚠️ Коробка кажется полной — опустоши для двойных очков!",
    "glass": "⚠️ Стекло кажется полным — опустоши и принеси!",
    "default": "⚠️ Продукт кажется полным — опустоши для полных очков.",
}


# ─────────────────────────────────────────────────────────────
# Prompt builder
# ─────────────────────────────────────────────────────────────

def build_prompt(token: str) -> str:
    return f"""Analyze this image and return ONLY valid JSON.

STRICT RULES:
- Focus ONLY on the largest, most centered object. Ignore background completely.
- If multiple different recyclable items are visible → set is_single_item=false.
- If the main object covers less than 25% of the frame → set too_far=true.
- Check if item looks USED: damaged label, dents, crushed shape, open cap → is_damaged=true.
- cosmetics_packaging → is_recyclable: false.
- STOCK PHOTO DETECTION: pure white/transparent background, studio lighting → is_stock_photo=true.
- REAL PHOTO REQUIRED: Must have real background, natural lighting, shadows or hand holding item.
- No screenshots, stock photos, or internet images accepted.
- TOKEN CHECK: Image MUST contain handwritten text '{token}' on paper visible in photo.
  If NOT visible → token_visible=false.

{{
  "is_recyclable": true/false,
  "is_stock_photo": true/false,
  "is_single_item": true/false,
  "too_far": true/false,
  "token_visible": true/false,
  "frame_coverage_pct": 0-100,
  "category": "plastic|glass|cardboard|metal|unknown",
  "brand": "brand name or UNKNOWN",
  "volume": "e.g. 1.5l or UNKNOWN",
  "color": "e.g. green or UNKNOWN",
  "is_empty": true/false,
  "is_damaged": true/false,
  "confidence": 0-100,
  "packaging_type": "beverage_container|food_packaging|cosmetics_packaging|other",
  "has_real_background": true/false
}}"""


# ─────────────────────────────────────────────────────────────
# review_queue yardımcısı
# ─────────────────────────────────────────────────────────────

def _add_review_queue(telegram_id: int, phash: str, file_id: str, a: dict, b: dict) -> int:
    import json as _json
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO review_queue (telegram_id, phash, file_id, result_a, result_b) "
            "VALUES (?, ?, ?, ?, ?)",
            (telegram_id, phash, file_id, _json.dumps(a), _json.dumps(b)),
        )
        conn.commit()
        return cur.lastrowid


# ─────────────────────────────────────────────────────────────
# Ana handler
# ─────────────────────────────────────────────────────────────

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    get_or_create_user(user.id, user.username or "", user.first_name or "")

    # Rate limit
    ok, msg = rate_limiter.check(user.id)
    if not ok:
        await update.message.reply_text(msg)
        return

    # Hesap yaşı
    age = get_account_age_days(user.id)
    if age < ACCOUNT_MIN_AGE_DAYS:
        await update.message.reply_text(
            f"⏳ Твой аккаунт слишком новый ({age} дн.). "
            f"Нужно минимум {ACCOUNT_MIN_AGE_DAYS} дн."
        )
        return

    # Günlük limit
    daily = get_user_daily_count(user.id)
    if daily >= DAILY_LIMIT:
        await update.message.reply_text(
            f"📵 Дневной лимит исчерпан ({DAILY_LIMIT} фото). Возвращайся завтра!"
        )
        return

    # Token kontrolü
    token = get_active_token(user.id)
    if not token:
        await update.message.reply_text(
            "❗ Сначала получи код командой /scan, запиши его на бумаге "
            "и сфотографируй вместе с мусором."
        )
        return

    # Fotoğrafı indir
    photo = update.message.photo[-1]
    file_id = photo.file_id
    file = await context.bot.get_file(file_id)
    photo_bytes = await file.download_as_bytearray()
    photo_bytes = bytes(photo_bytes)

    # SHA-256 ve pHash
    image_hash = hashlib.sha256(photo_bytes).hexdigest()
    if photo_hash_exists(image_hash):
        await update.message.reply_text("⚠️ Это фото уже было отправлено ранее.")
        return

    if file_id_exists(file_id):
        await update.message.reply_text("⚠️ Этот файл уже был использован.")
        return

    try:
        phash = get_perceptual_hash(photo_bytes)
    except Exception as e:
        logger.error("pHash hatası: %s", e)
        await update.message.reply_text("❌ Не удалось прочитать изображение. Попробуй ещё раз.")
        return

    if is_visually_duplicate(phash, get_user_phashes(user.id, limit=100)):
        await update.message.reply_text(
            "⚠️ Похожее фото уже было отправлено. Сдай другой предмет!"
        )
        return

    # AI analizi
    prompt = build_prompt(token)
    processing_msg = await update.message.reply_text("🔍 Анализирую фото...")

    try:
        gpt_result, gemini_result = await asyncio.gather(
            call_gpt(photo_bytes, prompt),      # FIX 2: ai_service'ten
            call_gemini(photo_bytes, prompt),   # FIX 2: ai_service'ten
            return_exceptions=True,
        )
    except Exception as e:
        logger.error("AI hatası: %s", e)
        await processing_msg.edit_text("❌ Сервис анализа временно недоступен. Попробуй позже.")
        return

    if isinstance(gpt_result, Exception):
        gpt_result = gemini_result if not isinstance(gemini_result, Exception) else {}
    if isinstance(gemini_result, Exception):
        gemini_result = gpt_result

    if not isinstance(gpt_result, dict) or not isinstance(gemini_result, dict):
        await processing_msg.edit_text("❌ AI вернул некорректный ответ. Попробуй ещё раз.")
        return

    # Token görünürlük kontrolü
    token_ok_a = gpt_result.get("token_visible", False)
    token_ok_b = gemini_result.get("token_visible", False)
    if not (token_ok_a or token_ok_b):
        await processing_msg.edit_text(
            "❌ Код не найден на фото!\n\n"
            f"Нужно написать <b>{token}</b> на бумаге и положить рядом с мусором.",
            parse_mode="HTML",
        )
        return

    # Geri dönüşümlü mü?
    recyclable_a = gpt_result.get("is_recyclable", False)
    recyclable_b = gemini_result.get("is_recyclable", False)
    if not (recyclable_a or recyclable_b):
        consume_token(user.id)
        await processing_msg.edit_text(
            "❌ Этот предмет не принимается для переработки.\n"
            "Отправляй пластик, стекло, металл или картон!"
        )
        return

    # AI konsensüs
    analyzer = ProductAnalyzer()
    analyzer.add(gpt_result)
    analyzer.add(gemini_result)
    fused = analyzer.fuse()

    consensus = resolve_ai_consensus(gpt_result, gemini_result)

    if consensus.get("needs_review"):
        review_id = _add_review_queue(user.id, phash, file_id, gpt_result, gemini_result)
        await notify_admins_review(
            context,
            review_id=review_id,
            telegram_id=user.id,
            result_a=gpt_result,
            result_b=gemini_result,
            phash=phash,
            file_id=file_id,
        )
        consume_token(user.id)
        await processing_msg.edit_text(
            "🔎 Фото отправлено на проверку модератору.\n"
            "Результат придёт в течение нескольких минут!"
        )
        return

    # Kategori ve paketleme tipi
    category = fused.get("category", "unknown")
    if category == "unknown":
        consume_token(user.id)
        await processing_msg.edit_text(
            "❓ Не удалось определить тип. Попробуй сфотографировать крупнее!"
        )
        return

    packaging_type = fused.get("packaging_type", "")
    if packaging_type and packaging_type not in ALLOWED_PACKAGING:
        consume_token(user.id)
        await processing_msg.edit_text(
            "❌ Косметика и другая упаковка не принимается.\n"
            "Нужны: бутылки, банки, коробки, стеклянная тара."
        )
        return

    # FIX 4: CATEGORY_DAY_LIMIT artık settings'ten geliyor
    cat_count = get_category_daily_count(user.id, category)
    if cat_count >= CATEGORY_DAY_LIMIT:
        await processing_msg.edit_text(
            f"📵 Лимит категории исчерпан ({CATEGORY_DAY_LIMIT} шт. в день).\n"
            "Сдай другой тип мусора!"
        )
        return

    is_empty = fused.get("is_empty", True)
    is_damaged = fused.get("is_damaged", False)
    brand = fused.get("brand", "UNKNOWN")
    volume = fused.get("volume", "UNKNOWN")
    color = fused.get("color", "UNKNOWN")

    fingerprint = build_fingerprint(brand=brand, volume=volume, color=color)
    if fingerprint_exists(user.id, fingerprint):
        await processing_msg.edit_text(
            "⚠️ Эта упаковка уже была сдана сегодня.\n"
            "Приноси другую бутылку!"
        )
        return

    # Fraud skoru
    fraud = compute_fraud_score(
        telegram_id=user.id,
        ai_data=fused,
        brand=brand,
        file_id=file_id,
    )

    if fraud["action"] == "reject":
        await processing_msg.edit_text(
            "🛡 Фото не прошло проверку безопасности.\n"
            "Убедись, что это реальное фото реального мусора!"
        )
        return

    if fraud["action"] == "review":
        review_id = _add_review_queue(user.id, phash, file_id, gpt_result, gemini_result)
        await notify_admins_review(
            context,
            review_id=review_id,
            telegram_id=user.id,
            result_a=gpt_result,
            result_b=gemini_result,
            phash=phash,
            file_id=file_id,
        )
        consume_token(user.id)
        await processing_msg.edit_text(
            "🔎 Фото на проверке (низкий показатель доверия).\n"
            "Результат придёт скоро!"
        )
        return

    # Puan hesapla
    base_points = get_points_for_category(category, is_empty)
    bonus = get_bonus_multiplier(brand)
    gps_mult = fraud.get("gps_multiplier", 1.0)
    final_points = max(1, round(base_points * bonus * gps_mult))

    # Kaydet
    rec = WasteRecord(
        telegram_id=user.id,
        image_hash=image_hash,
        phash=phash,
        file_id=file_id,
        points=final_points,
        brand=brand,
        fingerprint=fingerprint,
        category=category,
        is_empty=is_empty,
        is_damaged=is_damaged,
        raw_volume=volume,
        raw_color=color,
        fraud_score=fraud["score"],
        event_proof=fraud["event_proof"],
    )
    add_waste(rec)
    consume_token(user.id)

    # Yanıt oluştur
    emoji = _EMOJI.get(category, "♻️")
    cat_name = _CAT_RU.get(category, category)
    lines = [
        f"✅ <b>Принято!</b>",
        "",
        f"{emoji} {cat_name} — <b>+{final_points}</b> баллов",
    ]
    if brand and brand != "UNKNOWN":
        lines.append(f"🏷 Бренд: {brand}")
    if not is_empty:
        lines.append(_FULLNESS.get(category, _FULLNESS["default"]))
    if gps_mult > 1.0:
        lines.append("📍 GPS-бонус: ×1.2 (рядом с пунктом приёма!)")
    if bonus > 1.0:
        lines.append(f"⭐ Бонус бренда: ×{bonus}")

    await processing_msg.edit_text("\n".join(lines), parse_mode="HTML")