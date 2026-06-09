# services/scan_service.py — Paylaşılan foto analiz hattı (bot + web)

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid

from config.settings import DAILY_LIMIT, ACCOUNT_MIN_AGE_DAYS
from config.bonus_brands import get_bonus_multiplier
from database.db import get_connection
from handlers.photo import (
    ALLOWED_PACKAGING,
    CATEGORY_DAY_LIMIT,
    _call_gpt,
    _call_gemini,
    _rate_limiter,
)
from services.fingerprint import (
    ProductAnalyzer,
    build_fingerprint,
    get_perceptual_hash,
    is_visually_duplicate,
    resolve_ai_consensus,
)
from services.fraud_scorer import compute_fraud_score
from services.user_service import get_user, get_account_age_days
from services.waste_service import (
    WasteRecord,
    add_waste,
    file_id_exists,
    fingerprint_exists,
    get_category_daily_count,
    get_points_for_category,
    get_user_daily_count,
    get_user_phashes,
    photo_hash_exists,
)

logger = logging.getLogger(__name__)

_CAT_RU = {"plastic": "Пластик", "cardboard": "Картон", "glass": "Стекло", "metal": "Металл"}


def _fail(message: str, code: str = "rejected", **extra) -> dict:
    return {"ok": False, "status": code, "message": message, "points": 0, **extra}


def _ok(
    message: str,
    points: int,
    brand: str,
    category: str,
    fraud_score: float = 0.0,
    **extra,
) -> dict:
    return {
        "ok": True,
        "status": "accepted",
        "message": message,
        "points": points,
        "brand": brand,
        "category": category,
        "itemType": _CAT_RU.get(category, category),
        "fraudScore": fraud_score,
        **extra,
    }


def _add_review_queue(telegram_id: int, phash: str, file_id: str, a: dict, b: dict) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO review_queue (telegram_id, phash, file_id, result_a, result_b) "
            "VALUES (?, ?, ?, ?, ?)",
            (telegram_id, phash, file_id, json.dumps(a), json.dumps(b)),
        )
        conn.commit()
        return cur.lastrowid


async def process_photo_scan_async(
    telegram_id: int,
    photo_bytes: bytes,
    *,
    source: str = "web",
    skip_token_check: bool = True,
    gps_lat: float | None = None,
    gps_lon: float | None = None,
) -> dict:
    """Telegram bot ve web API için ortak tarama pipeline."""

    allowed, msg = _rate_limiter.check(telegram_id)
    if not allowed:
        return _fail(msg, "rate_limit")

    age = get_account_age_days(telegram_id)
    if age < ACCOUNT_MIN_AGE_DAYS:
        return _fail(
            f"Account too new ({age} days). Required: {ACCOUNT_MIN_AGE_DAYS} days.",
            "account_age",
        )

    daily = get_user_daily_count(telegram_id)
    if daily >= DAILY_LIMIT:
        return _fail(f"Daily limit reached ({DAILY_LIMIT} photos).", "daily_limit")

    file_id = f"{source}_{uuid.uuid4().hex}"
    if file_id_exists(file_id):
        return _fail("Duplicate upload.", "duplicate")

    image_hash = hashlib.sha256(photo_bytes).hexdigest()
    if photo_hash_exists(image_hash):
        return _fail("This photo was already submitted.", "duplicate_photo")

    try:
        phash = get_perceptual_hash(photo_bytes)
    except Exception as e:
        logger.error("pHash error: %s", e)
        return _fail("Could not read image.", "invalid_image")

    stored = get_user_phashes(telegram_id, limit=100)
    if is_visually_duplicate(phash, stored):
        return _fail(
            "This item was already submitted from another angle.",
            "visual_duplicate",
        )

    token = "WEBAPP" if skip_token_check else "ECO-0000"

    try:
        gpt_result, gemini_result = await asyncio.gather(
            _call_gpt(photo_bytes, token),
            _call_gemini(photo_bytes, token),
            return_exceptions=True,
        )
    except Exception as e:
        logger.error("AI error: %s", e)
        return _fail("AI services unavailable. Try later.", "ai_error")

    if isinstance(gpt_result, Exception):
        gpt_result = gemini_result if not isinstance(gemini_result, Exception) else {}
    if isinstance(gemini_result, Exception):
        gemini_result = gpt_result

    if not isinstance(gpt_result, dict) or not isinstance(gemini_result, dict):
        return _fail("AI returned invalid response.", "ai_error")

    analyzer = ProductAnalyzer()
    analyzer.add(gpt_result)
    analyzer.add(gemini_result)
    fused = analyzer.fuse()

    consensus = resolve_ai_consensus(gpt_result, gemini_result)
    if consensus.get("needs_review"):
        _add_review_queue(telegram_id, phash, file_id, gpt_result, gemini_result)
        return {
            "ok": False,
            "status": "review",
            "message": "Sent for manual review (AI disagreement).",
            "points": 0,
        }

    ai_data = {**consensus, **{
        k: fused[k]
        for k in (
            "brand", "volume", "color", "is_empty", "is_damaged", "confidence",
            "frame_coverage_pct", "is_single_item", "too_far", "token_visible",
            "is_stock_photo", "has_real_background",
        )
        if fused.get(k) is not None
    }}

    if not skip_token_check and not ai_data.get("token_visible", False):
        return _fail("Task code not visible on photo.", "token_missing")

    if ai_data.get("is_stock_photo") or not ai_data.get("has_real_background", True):
        return _fail("Stock photo detected. Use a real photo with background.", "stock_photo")

    if not ai_data.get("is_single_item", True):
        return _fail("Multiple items in frame. Photograph one item only.", "multi_item")

    if ai_data.get("too_far") or ai_data.get("frame_coverage_pct", 100) < 25:
        return _fail("Item too far. Move closer.", "too_far")

    packaging = ai_data.get("packaging_type", "")
    if not ai_data.get("is_recyclable", True) or (
        packaging and packaging not in ALLOWED_PACKAGING
    ):
        return _fail(
            "No recyclable packaging detected.",
            "not_recyclable",
        )

    category = (ai_data.get("category") or "unknown").strip().lower()
    is_empty = ai_data.get("is_empty", False)
    is_damaged = ai_data.get("is_damaged", False)
    brand = ai_data.get("brand", "UNKNOWN")

    cat_daily = get_category_daily_count(telegram_id, category)
    if cat_daily >= CATEGORY_DAY_LIMIT:
        cat_ru = _CAT_RU.get(category, category)
        return _fail(
            f"Daily limit for category «{cat_ru}» reached.",
            "category_limit",
        )

    fingerprint = build_fingerprint(
        brand=brand,
        volume=ai_data.get("volume", "UNKNOWN"),
        color=ai_data.get("color", "UNKNOWN"),
    )
    if fingerprint_exists(telegram_id, fingerprint):
        return _fail(
            f"You already submitted this packaging today ({brand}).",
            "fingerprint_duplicate",
        )

    fraud = compute_fraud_score(
        telegram_id=telegram_id,
        ai_data={
            "is_empty": is_empty,
            "is_damaged": is_damaged,
            "confidence": ai_data.get("confidence", 50),
        },
        brand=brand,
        file_id=file_id,
        gps_lat=gps_lat,
        gps_lon=gps_lon,
    )

    if fraud["action"] == "reject":
        return _fail(
            "Photo failed fraud check.",
            "fraud_reject",
            fraudScore=fraud["score"],
        )

    if fraud["action"] == "review":
        _add_review_queue(telegram_id, phash, file_id, gpt_result, gemini_result)
        return {
            "ok": False,
            "status": "review",
            "message": "Sent for manual review.",
            "points": 0,
            "fraudScore": fraud["score"],
        }

    base_points = get_points_for_category(category, is_empty)
    bonus_mult, is_bonus = get_bonus_multiplier(brand)
    gps_mult = fraud["gps_multiplier"]
    points = int(base_points * bonus_mult * gps_mult)

    add_waste(WasteRecord(
        telegram_id=telegram_id,
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

    user = get_user(telegram_id)
    total_pts = user["total_points"] if user else points

    msg = f"+{points} points — {brand}"
    if is_bonus:
        msg += " (brand bonus)"
    if gps_mult > 1.0:
        msg += " (GPS bonus)"

    return _ok(
        msg,
        points=points,
        brand=brand,
        category=category,
        fraud_score=fraud["score"],
        totalPoints=total_pts,
        dailyCount=daily + 1,
    )


def process_photo_scan(
    telegram_id: int,
    photo_bytes: bytes,
    **kwargs,
) -> dict:
    """Flask sync wrapper."""
    try:
        asyncio.get_running_loop()
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(
                lambda: asyncio.run(
                    process_photo_scan_async(telegram_id, photo_bytes, **kwargs)
                )
            ).result()
    except RuntimeError:
        return asyncio.run(
            process_photo_scan_async(telegram_id, photo_bytes, **kwargs)
        )
