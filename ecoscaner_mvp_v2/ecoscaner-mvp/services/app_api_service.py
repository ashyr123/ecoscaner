# services/app_api_service.py — Mobil web app JSON verisi

from __future__ import annotations

import os
from database.db import get_connection
from services.user_service import get_user, get_user_rank
from services.store_service import get_active_items


LEVEL_THRESHOLDS = [0, 50, 200, 500]
LEVEL_LABELS = {
    1: "🌰 Начинающий",
    2: "🌱 Эко-новичок",
    3: "🌿 Эко-активист",
    4: "🌳 Эко-мастер",
}


def get_level_info(earned_points: int) -> dict:
    level = 1
    for i, threshold in enumerate(LEVEL_THRESHOLDS):
        if earned_points >= threshold:
            level = i + 1
    level = min(level, len(LEVEL_LABELS))
    return {"level": level, "levelLabel": LEVEL_LABELS.get(level, LEVEL_LABELS[1])}


def resolve_telegram_id(requested_id: int | None) -> int | None:
    """MVP: ?user_id= veya APP_DEV_USER_ID veya DB'deki ilk kullanıcı."""
    if requested_id:
        return requested_id
    env_id = os.getenv("APP_DEV_USER_ID", "").strip()
    if env_id.isdigit():
        return int(env_id)
    with get_connection() as conn:
        row = conn.execute(
            "SELECT telegram_id FROM users ORDER BY id ASC LIMIT 1"
        ).fetchone()
        return int(row["telegram_id"]) if row else None


def get_profile(telegram_id: int) -> dict:
    user = get_user(telegram_id)
    if not user:
        return {
            "found": False,
            "telegramId": telegram_id,
            "firstName": "Eco-Hero",
            "username": "",
            "totalPoints": 0,
            "totalEarnedPoints": 0,
            "totalWastes": 0,
            "level": 1,
            "levelLabel": LEVEL_LABELS[1],
            "rank": None,
            "savedWaterLiters": 0.0,
        }

    earned = user.get("total_earned_points") or 0
    wastes = user.get("total_wastes") or 0
    level_info = get_level_info(earned)
    rank_info = get_user_rank(telegram_id, weekly=False)

    return {
        "found": True,
        "telegramId": telegram_id,
        "firstName": user.get("first_name") or "Eco-Hero",
        "username": user.get("username") or "",
        "totalPoints": user.get("total_points") or 0,
        "totalEarnedPoints": earned,
        "totalWastes": wastes,
        "level": level_info["level"],
        "levelLabel": level_info["levelLabel"],
        "rank": rank_info["rank"] if rank_info else None,
        "savedWaterLiters": round(wastes * 0.25, 1),
    }


def get_user_activity(telegram_id: int, limit: int = 20) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT brand, points, category, created_at
            FROM wastes
            WHERE telegram_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (telegram_id, limit),
        ).fetchall()
    return [
        {
            "brand": r["brand"] or "UNKNOWN",
            "points": r["points"] or 0,
            "category": r["category"] or "",
            "createdAt": r["created_at"],
        }
        for r in rows
    ]


def get_leaderboard_data(telegram_id: int | None, limit: int = 100) -> dict:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT telegram_id, first_name, username,
                   total_points, total_wastes, total_earned_points
            FROM users
            ORDER BY total_earned_points DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    entries = []
    for i, r in enumerate(rows):
        u = dict(r)
        tid = u.get("telegram_id")
        earned = u.get("total_earned_points") or u.get("total_points") or 0
        entries.append({
            "rank": i + 1,
            "telegramId": tid,
            "firstName": u.get("first_name") or "Anonymous",
            "username": u.get("username") or "",
            "points": earned,
            "totalWastes": u.get("total_wastes") or 0,
            "isCurrentUser": telegram_id is not None and tid == telegram_id,
        })

    current_rank = None
    if telegram_id:
        rank_info = get_user_rank(telegram_id, weekly=False)
        if rank_info:
            current_rank = {
                "rank": rank_info["rank"],
                "points": rank_info["total_points"] or 0,
                "totalWastes": rank_info["total_wastes"] or 0,
            }

    return {"entries": entries, "currentUser": current_rank}


def get_store_data(telegram_id: int | None) -> dict:
    balance = 0
    if telegram_id:
        user = get_user(telegram_id)
        if user:
            balance = user.get("total_points") or 0

    items = []
    for item in get_active_items():
        price = item.get("price") or 0
        items.append({
            "id": item["id"],
            "name": item["name"],
            "description": item.get("description") or "",
            "price": price,
            "stock": item.get("stock", -1),
            "canAfford": balance >= price,
        })

    return {"balance": balance, "items": items}
