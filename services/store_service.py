# services/store_service.py

from __future__ import annotations

from typing import Optional
from database.db import get_connection
# spend_points import edilmiş ama kullanılmıyor → kaldırıldı


# ─────────────────────────────────────────────────────────────
# Seed
# ─────────────────────────────────────────────────────────────

def seed_default_items() -> None:
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM store_items")
        if c.fetchone()[0] == 0:
            c.executemany(
                "INSERT INTO store_items (name, description, price, stock, is_active) VALUES (?, ?, ?, ?, 1)",
                [
                    ("🌟 Золотой значок",    "Особый значок в профиле",               50, -1),
                    ("💬 Особый статус",     "Красивая фраза в твоём профиле",         30, -1),
                    ("🎟 Билет на розыгрыш", "1 билет для участия в розыгрыше призов", 10, -1),
                ],
            )
            conn.commit()


# ─────────────────────────────────────────────────────────────
# Okuma
# ─────────────────────────────────────────────────────────────

def get_active_items() -> list[dict]:
    with get_connection() as conn:
        c = conn.cursor()
        c.execute(
            """
            SELECT id, name, description, price, stock
            FROM store_items
            WHERE is_active = 1
              AND (stock = -1 OR stock > 0)
            ORDER BY price ASC
            """
        )
        return [dict(row) for row in c.fetchall()]


def get_item_by_id(item_id: int) -> Optional[dict]:
    with get_connection() as conn:
        c = conn.cursor()
        c.execute(
            """
            SELECT id, name, description, price, stock
            FROM store_items
            WHERE id = ? AND is_active = 1
              AND (stock = -1 OR stock > 0)
            """,
            (item_id,),
        )
        row = c.fetchone()
        return dict(row) if row else None


# ─────────────────────────────────────────────────────────────
# Satın alma — atomik işlem
# ─────────────────────────────────────────────────────────────

def buy_item(telegram_id: int, item_id: int) -> tuple[bool, str]:
    item = get_item_by_id(item_id)
    if not item:
        return False, "❌ Товар не найден или недоступен."

    price = item["price"]

    with get_connection() as conn:
        c = conn.cursor()

        c.execute(
            "SELECT total_points FROM users WHERE telegram_id = ?",
            (telegram_id,),
        )
        row = c.fetchone()
        if not row or row["total_points"] < price:
            return False, "❌ Недостаточно баллов на счету."

        c.execute(
            "UPDATE users SET total_points = total_points - ? WHERE telegram_id = ?",
            (price, telegram_id),
        )
        c.execute(
            "INSERT INTO purchases (telegram_id, item_id, points_spent) VALUES (?, ?, ?)",
            (telegram_id, item_id, price),
        )

        if item["stock"] != -1:
            c.execute(
                "UPDATE store_items SET stock = stock - 1 WHERE id = ?",
                (item_id,),
            )

        conn.commit()

    return True, f"✅ Ты успешно получил: <b>{item['name']}</b>!"


# ─────────────────────────────────────────────────────────────
# Satın alma geçmişi
# ─────────────────────────────────────────────────────────────

def get_user_purchases(telegram_id: int) -> list[dict]:
    with get_connection() as conn:
        c = conn.cursor()
        c.execute(
            """
            SELECT s.name, s.description, p.points_spent, p.created_at
            FROM purchases p
            JOIN store_items s ON p.item_id = s.id
            WHERE p.telegram_id = ?
            ORDER BY p.created_at DESC
            """,
            (telegram_id,),
        )
        return [dict(row) for row in c.fetchall()]