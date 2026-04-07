# handlers/photo.py — EcoScaner Telegram handler

import asyncio
import hashlib
import json
import logging
import time

from telegram import Update
from telegram.ext import ContextTypes

from config.settings import (
    OPENROUTER_API_KEY,
    DAILY_LIMIT,
    ACCOUNT_MIN_AGE_DAYS,
)
from config.bonus_brands import get_bonus_multiplier   # ← YENİ

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
from database.db import get_connection
from handlers.admin_review import notify_admins_review  # ← YENİ

import httpx

logger = logging.getLogger(__name__)

CATEGORY_DAY_LIMIT = 2
ALLOWED_PACKAGING  = {"beverage_container", "food_packaging"}

# ─────────────────────────────────────────────────────────────
# Emoji / metin tabloları
# ─────────────────────────────────────────────────────────────

_EMOJI  = {"plastic": "🧴", "cardboard": "📦", "glass": "🍶", "metal": "🥫"}
_CAT_RU = {"plastic": "Пластик", "cardboard": "Картон", "glass": "Стекло", "metal": "Металл"}
_FULLNESS = {
    "plastic":   "⚠️ Бутылка кажется полной — опустоши для полных очков!",
    "cardboard": "⚠️ Коробка кажется полной — опустоши для двойных очков!",
    "glass":     "⚠️ Стекло кажется полным — опустоши и принеси!",
    "default":   "⚠️ Продукт кажется полным — опустоши для полных очков.",
}

# ─────────────────────────────────────────────────────────────
# Rate Limiter
# ─────────────────────────────────────────────────────────────

class _RateLimiter:
    def __init__(self, max_per_minute: int = 5):
        self.max  = max_per_minute
        self._log: dict[int, list[float]] = {}

    def check(self, user_id: int) -> tuple[bool, str]:
        now    = time.time()
        cutoff = now - 60.0
        recent = [t for t in self._log.get(user_id, []) if t > cutoff]
        self._log[user_id] = recent
        if len(recent) >= self.max:
            wait = int(60 - (now - recent[0])) + 1
            return False, f"⏳ Слишком быстро! Подожди {wait} сек."
        self._log[user_id].append(now)
        return True, "ok"

_rate_limiter = _RateLimiter(max_per_minute=5)

# ─────────────────────────────────────────────────────────────
# Prompt
# ─────────────────────────────────────────────────────────────

PROMPT = """Analyze this image and return ONLY valid JSON.

STRICT RULES:
- Focus ONLY on the largest, most centered object. Ignore background completely.
- If multiple different recyclable items are visible → set is_single_item=false, do not analyze further.
- If the main object covers less than 25% of the frame → set too_far=true.
- Check if item looks USED: damaged label, dents, crushed shape, open cap → is_damaged=true.
- cosmetics_packaging → is_recyclable: false.
- No screenshots or stock photos accepted.

{
  "is_recyclable": true/false,
  "is_single_item": true/false,
  "too_far": true/false,
  "frame_coverage_pct": 0-100,
  "category": "plastic|glass|cardboard|metal|unknown",
  "brand": "brand name or UNKNOWN",
  "volume": "e.g. 1.5l or UNKNOWN",
  "color": "e.g. green or UNKNOWN",
  "is_empty": true/false,
  "is_damaged": true/false,
  "confidence": 0-100,
  "packaging_type": "beverage_container|food_packaging|cosmetics_packaging|other"
}"""

# ─────────────────────────────────────────────────────────────
# AI çağrıları
# ─────────────────────────────────────────────────────────────

async def _call_ai(photo_bytes: bytes, model: str) -> dict:
    import base64
    b64 = base64.b64encode(photo_bytes).decode()
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type":  "application/json",
            },
            json={
                "model": model,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "text",      "text": PROMPT},
                        {"type": "image_url", "image_url": {
                            "url": f"data:image/jpeg;base64,{b64}"
                        }},
                    ],
                }],
                "max_tokens": 300,
            },
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        start = content.find("{")
        end   = content.rfind("}") + 1
        return json.loads(content[start:end])

async def _call_gpt(photo_bytes: bytes)    -> dict: return await _call_ai(photo_bytes, "openai/gpt-4o-mini")
async def _call_gemini(photo_bytes: bytes) -> dict: return await _call_ai(photo_bytes, "google/gemini-2.0-flash-001")

# ─────────────────────────────────────────────────────────────
# DB yardımcıları
# ─────────────────────────────────────────────────────────────

async def _get_phashes(user_id: int) -> list[str]:
    return get_user_phashes(user_id, limit=100)

async def _fp_exists(user_id: int, fp: str) -> bool:
    return fingerprint_exists(user_id, fp)

async def _daily_count(user_id: int) -> int:
    return get_user_daily_count(user_id)

async def _total_points(user_id: int) -> int:
    user = get_user(user_id)
    return user["total_points"] if user else 0

async def _add_to_review_queue(
    context,
    user_id: int,
    phash: str,
    a: dict,
    b: dict,
) -> None:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO review_queue (telegram_id, phash, result_a, result_b)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, phash, json.dumps(a), json.dumps(b)),
        )
        conn.commit()
        review_id = cursor.lastrowid

    # ← YENİ: Admin'e Telegram bildirimi gönder
    await notify_admins_review(context, review_id, user_id, a, b, phash)

async def _flag_suspicious(user_id: int, reason: str, score: float, daily: int) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO fraud_flags (telegram_id, reason, score, daily_count)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, reason, score, daily),
        )
        conn.commit()

# ─────────────────────────────────────────────────────────────
# Başarı mesajı
# ─────────────────────────────────────────────────────────────

def _success_msg(
    category: str,
    is_empty: bool,
    points: int,
    base_points: int,
    daily: int,
    total_pts: int,
    fraud_score: float,
    gps_bonus: str,
    brand_bonus: bool,
    brand: str,
) -> str:
    emoji  = _EMOJI.get(category, "♻️")
    cat_ru = _CAT_RU.get(category, category.capitalize())
    lines  = [
        "✅ Отлично! Мусор принят!",
        f"🗂 Тип: {cat_ru} {emoji}",
    ]

    # Bonus gösterimi
    if brand_bonus and points > base_points:
        bonus_pts = points - base_points
        lines.append(f"💎 +{base_points} баллов + 🎁 +{bonus_pts} бонус за {brand}!")
    else:
        lines.append(f"💎 +{points} баллов начислено!{gps_bonus}")

    lines += [
        f"📊 Сегодня отправлено: {daily}/{DAILY_LIMIT}",
        f"🏆 Всего баллов: {total_pts}",
        f"🛡️ Доверие: {int(fraud_score * 100)}%",
        "🔒 Проверено двумя ИИ",
    ]

    if not is_empty:
        lines.append(_FULLNESS.get(category, _FULLNESS["default"]))

    lines.append("\nСпасибо! 🌱")
    return "\n".join(lines)

# ─────────────────────────────────────────────────────────────
# Ana handler
# ─────────────────────────────────────────────────────────────

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id  = update.effective_user.id
    username = update.effective_user.username or ""
    get_or_create_user(user_id, username, update.effective_user.first_name or "")

    # K0: Rate limit
    allowed, msg = _rate_limiter.check(user_id)
    if not allowed:
        await update.message.reply_text(msg)
        return

    # K1: Hesap yaşı
    age = get_account_age_days(user_id)
    if age < ACCOUNT_MIN_AGE_DAYS:
        await update.message.reply_text(
            f"⏳ Аккаунт создан {age} дн. назад.\n"
            f"Принимать мусор начнём через {ACCOUNT_MIN_AGE_DAYS - age} дн. 🔒"
        )
        return

    # K2: Günlük limit
    daily = await _daily_count(user_id)
    if daily >= DAILY_LIMIT:
        await update.message.reply_text(
            f"📵 Дневной лимит ({DAILY_LIMIT} фото) исчерпан.\nВозвращайся завтра! 🌅"
        )
        return

    # Fotoğraf indir
    tg_file     = update.message.photo[-1]
    file_id     = tg_file.file_id
    photo_file  = await tg_file.get_file()
    photo_bytes = bytes(await photo_file.download_as_bytearray())

    # K3: file_id kontrolü
    if file_id_exists(file_id):
        await update.message.reply_text(
            "🤖 Это фото уже отправлялось ранее.\nСделай новый снимок прямо сейчас!"
        )
        await _flag_suspicious(user_id, f"Duplicate file_id: {file_id}", 0.0, daily)
        return

    # K4: SHA256
    image_hash = hashlib.sha256(photo_bytes).hexdigest()
    if photo_hash_exists(image_hash):
        await update.message.reply_text("🔁 Это фото уже было отправлено ранее.\nПришли другой!")
        return

    # K5: Perceptual hash
    try:
        phash = get_perceptual_hash(photo_bytes)
    except Exception as e:
        logger.error("pHash hatası: %s", e)
        await update.message.reply_text("❌ Фото не читается. Попробуй ещё раз.")
        return

    stored_hashes = await _get_phashes(user_id)
    if is_visually_duplicate(phash, stored_hashes):
        await update.message.reply_text(
            "📷 Этот предмет уже был отправлен с другого ракурса!\n"
            "Разные фото одного товара не дают дополнительных очков."
        )
        return

    # K6: AI analizi
    await update.message.reply_text("🔍 Фото анализируется...\n🤖 ИИ проверяет...")

    try:
        gpt_result, gemini_result = await asyncio.gather(
            _call_gpt(photo_bytes),
            _call_gemini(photo_bytes),
            return_exceptions=True,
        )
    except Exception as e:
        logger.error("AI hatası: %s", e)
        await update.message.reply_text("❌ ИИ не ответил. Попробуй позже.")
        return

    if isinstance(gpt_result, Exception):
        logger.warning("GPT hata, Gemini ile devam: %s", gpt_result)
        gpt_result = gemini_result
    if isinstance(gemini_result, Exception):
        logger.warning("Gemini hata, GPT ile devam: %s", gemini_result)
        gemini_result = gpt_result

    analyzer = ProductAnalyzer()
    analyzer.add(gpt_result)
    analyzer.add(gemini_result)
    fused = analyzer.fuse()

    consensus = resolve_ai_consensus(gpt_result, gemini_result)
    if consensus.get("needs_review"):
        await _add_to_review_queue(context, user_id, phash, gpt_result, gemini_result)
        await update.message.reply_text(
            "🔎 Два ИИ дали разные результаты.\n"
            "Отправлено на проверку — ответ в течение 24 часов."
        )
        return

    ai_data = {**consensus, **{
        k: fused[k]
        for k in ("brand", "volume", "color", "is_empty",
                  "is_damaged", "confidence", "frame_coverage_pct",
                  "is_single_item", "too_far")
        if fused.get(k) is not None
    }}

    # K6a: Tek ürün
    if not ai_data.get("is_single_item", True):
        await update.message.reply_text(
            "📸 На фото несколько предметов.\nПожалуйста, фотографируй каждый товар отдельно!"
        )
        return

    # K6b: Uzaklık
    if ai_data.get("too_far") or ai_data.get("frame_coverage_pct", 100) < 25:
        await update.message.reply_text(
            "📏 Товар слишком далеко от камеры.\nПоднеси ближе и сфотографируй снова!"
        )
        return

    # Kozmetik / kabul edilmez
    packaging = ai_data.get("packaging_type", "")
    if not ai_data.get("is_recyclable", True) or (packaging and packaging not in ALLOWED_PACKAGING):
        await update.message.reply_text(
            "❌ На фото не обнаружен перерабатываемый мусор.\n\n"
            "Принимаем:\n"
            "🧴 Пластиковая бутылка — 5 баллов\n"
            "🍶 Стеклянная бутылка — 8 баллов\n"
            "🥫 Жестяная банка — 6 баллов\n"
            "📦 Картонная коробка — 3 балла"
        )
        return

    category   = (ai_data.get("category") or "unknown").strip().lower()
    is_empty   = ai_data.get("is_empty", False)
    is_damaged = ai_data.get("is_damaged", False)
    brand      = ai_data.get("brand", "UNKNOWN")

    # K7: Kategori günlük limiti
    cat_daily = get_category_daily_count(user_id, category)
    if cat_daily >= CATEGORY_DAY_LIMIT:
        cat_ru = _CAT_RU.get(category, category)
        await update.message.reply_text(
            f"⚠️ Сегодня ты уже сдал {CATEGORY_DAY_LIMIT} шт. категории «{cat_ru}».\n"
            "Принеси другой тип упаковки! ♻️"
        )
        return

    # K8: Fingerprint
    fingerprint = build_fingerprint(
        brand=brand,
        volume=ai_data.get("volume", "UNKNOWN"),
        color=ai_data.get("color", "UNKNOWN"),
    )
    if await _fp_exists(user_id, fingerprint):
        await update.message.reply_text(
            f"⚠️ Эту упаковку ({brand} {ai_data.get('volume','UNKNOWN')}) ты уже сдавал сегодня!\n"
            "Принеси другую. ♻️"
        )
        return

    # K9: Fraud scoring
    gps_lat = context.user_data.get("gps_lat")
    gps_lon = context.user_data.get("gps_lon")

    fraud = compute_fraud_score(
        telegram_id=user_id,
        ai_data={"is_empty": is_empty, "is_damaged": is_damaged, "confidence": ai_data.get("confidence", 50)},
        brand=brand,
        file_id=file_id,
        gps_lat=gps_lat,
        gps_lon=gps_lon,
    )

    if fraud["action"] == "reject":
        await _flag_suspicious(user_id, f"fraud_score={fraud['score']}", fraud["score"], daily)
        await update.message.reply_text("🚫 Фото не прошло проверку.\nПопробуй отправить другое фото.")
        return

    if fraud["action"] == "review":
        await _add_to_review_queue(context, user_id, phash, gpt_result, gemini_result)
        await update.message.reply_text("🔎 Фото отправлено на проверку.\nОтвет придёт в течение 24 часов.")
        return

    # ── YENİ: Bonus marka kontrolü ───────────────────────────
    base_points    = get_points_for_category(category, is_empty)
    bonus_mult, is_bonus = get_bonus_multiplier(brand)
    gps_mult       = fraud["gps_multiplier"]
    points         = int(base_points * bonus_mult * gps_mult)
    gps_bonus      = " 🌍+GPS" if gps_mult > 1.0 else ""

    add_waste(WasteRecord(
        telegram_id=user_id,
        image_hash=image_hash,
        phash=phash,
        file_id=file_id,
        points=points,
        brand=brand,
        fingerprint=fingerprint,
        category=category,
        is_empty=is_empty,
        is_damaged=is_damaged,
        raw_volume=ai_data.get("volume", ""),
        raw_color=ai_data.get("color", ""),
        fraud_score=fraud["score"],
        event_proof=fraud["event_proof"],
        gps_lat=gps_lat,
        gps_lon=gps_lon,
    ))

    daily     = await _daily_count(user_id)
    total_pts = await _total_points(user_id)

    await update.message.reply_text(
        _success_msg(
            category, is_empty, points, base_points,
            daily, total_pts, fraud["score"],
            gps_bonus, is_bonus, brand,
        )
    )

    if daily > 15:
        await _flag_suspicious(user_id, f"Yüksek günlük: {daily}", fraud["score"], daily)

    logger.info(
        "Kabul → user_id=%d cat=%s pts=%d (bonus=%s) daily=%d fraud=%.3f",
        user_id, category, points, is_bonus, daily, fraud["score"],
    )