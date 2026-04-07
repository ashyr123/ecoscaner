# services/fraud_scorer.py

import hashlib
from datetime import datetime, date, timezone
from math import radians, cos, sin, asin, sqrt

from database.db import get_connection
from services.user_service import get_user


def build_event_proof(file_id: str, user_id: int) -> str:
    today = date.today().isoformat()
    return hashlib.sha256(f"{file_id}:{user_id}:{today}".encode()).hexdigest()


def check_file_id_duplicate(file_id: str, telegram_id: int) -> bool:
    """True = daha önce görüldü (hile) | False = temiz"""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM wastes WHERE file_id = ?",
            (file_id,),
        ).fetchone()
    return (row["cnt"] if row else 0) > 0


def _gps_rate(telegram_id: int) -> float:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN gps_lat IS NOT NULL THEN 1 ELSE 0 END) AS gps_count
            FROM wastes
            WHERE telegram_id = ?
            """,
            (telegram_id,),
        ).fetchone()
    if not row or not row["total"]:
        return 0.0
    return row["gps_count"] / row["total"]


def score_user_trust(telegram_id: int) -> float:
    user = get_user(telegram_id)
    if not user:
        return 0.0

    score = 0.0
    try:
        created = datetime.fromisoformat(str(user["created_at"]))
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age = (datetime.now(tz=timezone.utc) - created).days
    except Exception:
        age = 0

    if   age >= 30: score += 0.35
    elif age >= 14: score += 0.25
    elif age >= 7:  score += 0.15

    total = user.get("total_wastes", 0)
    if   total >= 50: score += 0.30
    elif total >= 20: score += 0.20
    elif total >= 5:  score += 0.10

    score += _gps_rate(telegram_id) * 0.35
    return min(1.0, score)


def score_used_product(ai_data: dict) -> float:
    score = 0.5
    if ai_data.get("is_empty"):   score += 0.25
    if ai_data.get("is_damaged"): score += 0.25
    conf = ai_data.get("confidence", 50)
    if   conf > 90: score -= 0.10   # stok görsel şüphesi
    elif conf < 60: score -= 0.05
    return max(0.0, min(1.0, score))


def score_neighborhood(
    telegram_id: int, brand: str, gps_lat, gps_lon
) -> float:
    if not gps_lat or not gps_lon:
        return 0.5

    with get_connection() as conn:
        same = conn.execute(
            """
            SELECT COUNT(*) AS cnt FROM wastes
            WHERE DATE(created_at) = DATE('now')
              AND LOWER(brand) = LOWER(?)
              AND gps_lat BETWEEN ? AND ?
              AND gps_lon BETWEEN ? AND ?
              AND telegram_id != ?
            """,
            (brand,
             gps_lat - .05, gps_lat + .05,
             gps_lon - .05, gps_lon + .05,
             telegram_id),
        ).fetchone()["cnt"]

        total = conn.execute(
            """
            SELECT COUNT(*) AS cnt FROM wastes
            WHERE DATE(created_at) = DATE('now')
              AND gps_lat BETWEEN ? AND ?
              AND gps_lon BETWEEN ? AND ?
            """,
            (gps_lat - .05, gps_lat + .05,
             gps_lon - .05, gps_lon + .05),
        ).fetchone()["cnt"]

    if total < 5: return 0.6
    r = same / total
    if   r > 0.60: return 0.1
    elif r > 0.40: return 0.4
    elif r > 0.20: return 0.7
    else:          return 1.0


def get_gps_multiplier(gps_lat, gps_lon) -> float:
    if not gps_lat or not gps_lon:
        return 1.0

    def _haversine(la1, lo1, la2, lo2) -> float:
        R = 6_371_000
        a = (sin(radians(la2 - la1) / 2) ** 2
             + cos(radians(la1)) * cos(radians(la2))
             * sin(radians(lo2 - lo1) / 2) ** 2)
        return R * 2 * asin(sqrt(a))

    with get_connection() as conn:
        pts = conn.execute(
            "SELECT lat, lon FROM recycling_points"
        ).fetchall()

    for p in pts:
        if _haversine(gps_lat, gps_lon, p["lat"], p["lon"]) < 500:
            return 1.2
    return 1.0


_W = {"used": 0.30, "trust": 0.35, "hood": 0.20, "file": 0.15}


def compute_fraud_score(
    telegram_id: int,
    ai_data: dict,
    brand: str,
    file_id: str,
    gps_lat=None,
    gps_lon=None,
) -> dict:
    s_used  = score_used_product(ai_data)
    s_trust = score_user_trust(telegram_id)
    s_hood  = score_neighborhood(telegram_id, brand, gps_lat, gps_lon)
    s_file  = 1.0 if file_id else 0.0

    score = (s_used  * _W["used"]
             + s_trust * _W["trust"]
             + s_hood  * _W["hood"]
             + s_file  * _W["file"])

    if   score >= 0.35: action = "accept"
    elif score >= 0.20: action = "review"
    else:               action = "reject"

    return {
        "score":          round(score, 3),
        "action":         action,
        "gps_multiplier": get_gps_multiplier(gps_lat, gps_lon),
        "event_proof":    build_event_proof(file_id, telegram_id),
        "signals": {
            "used_product":  round(s_used,  3),
            "user_trust":    round(s_trust, 3),
            "neighborhood":  round(s_hood,  3),
            "file_id_proof": s_file,
        },
    }