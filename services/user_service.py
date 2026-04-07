# services/user_service.py

from __future__ import annotations

from datetime import datetime, timezone
from database.db import get_connection


# ─────────────────────────────────────────────────────────────
# Kullanıcı oluşturma / getirme
# ─────────────────────────────────────────────────────────────

def get_or_create_user(telegram_id: int, username: str, first_name: str) -> None:
    """INSERT OR IGNORE — TOCTOU race condition yok."""
    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO users
                (telegram_id, username, first_name,
                 total_points, total_earned_points, total_wastes)
            VALUES (?, ?, ?, 0, 0, 0)
            """,
            (telegram_id, username or "", first_name or ""),
        )
        conn.commit()


def get_user(telegram_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE telegram_id = ?",
            (telegram_id,),
        ).fetchone()
        return dict(row) if row else None


# ─────────────────────────────────────────────────────────────
# Hesap yaşı
# ─────────────────────────────────────────────────────────────

def get_account_age_days(telegram_id: int) -> int:
    """Hesabın kaç günlük olduğunu döner."""
    user = get_user(telegram_id)
    if not user or not user.get("created_at"):
        return 0
    try:
        created = datetime.fromisoformat(str(user["created_at"]))
        # SQLite datetime('now') → UTC saklar.
        # Karşılaştırma için her ikisini de UTC'ye çek.
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        now = datetime.now(tz=timezone.utc)
        return max(0, (now - created).days)
    except (ValueError, TypeError):
        return 0


# ─────────────────────────────────────────────────────────────
# Puan işlemleri
# ─────────────────────────────────────────────────────────────

def add_points(telegram_id: int, points: int) -> int:
    """Puan ekler, güncel bakiyeyi döner."""
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE users
            SET total_points        = total_points + ?,
                total_earned_points = total_earned_points + ?
            WHERE telegram_id = ?
            """,
            (points, points, telegram_id),
        )
        conn.commit()
        row = conn.execute(
            "SELECT total_points FROM users WHERE telegram_id = ?",
            (telegram_id,),
        ).fetchone()
        return row["total_points"] if row else 0


def spend_points(telegram_id: int, cost: int) -> bool:
    """
    Puan harcar. Yeterli bakiye yoksa False döner.
    Not: store_service.buy_item() kendi atomik transaction'ında
    bakiyeyi kontrol edip düşürüyor — bu fonksiyon harici kullanım için.
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT total_points FROM users WHERE telegram_id = ?",
            (telegram_id,),
        ).fetchone()
        if not row or (row["total_points"] or 0) < cost:
            return False
        conn.execute(
            "UPDATE users SET total_points = total_points - ? WHERE telegram_id = ?",
            (cost, telegram_id),
        )
        conn.commit()
        return True


def get_balance(telegram_id: int) -> tuple[int, int]:
    """(mevcut_bakiye, toplam_kazanılan) döner."""
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT total_points, total_earned_points
            FROM users WHERE telegram_id = ?
            """,
            (telegram_id,),
        ).fetchone()
        if not row:
            return 0, 0
        return row["total_points"] or 0, row["total_earned_points"] or 0


# ─────────────────────────────────────────────────────────────
# Liderlik tablosu
# ─────────────────────────────────────────────────────────────

def get_top_users(limit: int = 10) -> list[dict]:
    """Tüm zamanlar — toplam kazanılan puana göre."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT first_name, username,
                   total_points, total_wastes, total_earned_points
            FROM users
            ORDER BY total_earned_points DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_weekly_top_users(limit: int = 10) -> list[dict]:
    """Son 7 gün — wastes tablosundan gerçek zamanlı hesaplanır."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT u.first_name,
                   u.username,
                   COUNT(w.id)   AS total_wastes,
                   SUM(w.points) AS total_points
            FROM wastes w
            JOIN users u ON w.telegram_id = u.telegram_id
            WHERE DATE(w.created_at) >= DATE('now', '-7 days')
            GROUP BY w.telegram_id
            ORDER BY total_points DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


# ─────────────────────────────────────────────────────────────
# Kullanıcı sıralaması
# ─────────────────────────────────────────────────────────────

def get_user_rank(telegram_id: int, weekly: bool = False) -> dict | None:
    """
    Kullanıcının sıralamasını döner.
    weekly=True → son 7 günlük sıralama.
    Listede yoksa None.
    """
    with get_connection() as conn:
        if weekly:
            rows = conn.execute(
                """
                SELECT telegram_id,
                       COUNT(*)    AS total_wastes,
                       SUM(points) AS total_points
                FROM wastes
                WHERE DATE(created_at) >= DATE('now', '-7 days')
                GROUP BY telegram_id
                ORDER BY total_points DESC
                """
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT telegram_id,
                       total_earned_points AS total_points,
                       total_wastes
                FROM users
                ORDER BY total_earned_points DESC
                """
            ).fetchall()

        # Loop'u with bloğu içinde tut —
        # Row nesneleri bağlantı kapandıktan sonra da erişilebilir
        # ama bağlantı açıkken yapmak daha güvenli.
        for i, row in enumerate(rows):
            if row["telegram_id"] == telegram_id:
                return {
                    "rank":         i + 1,
                    "total_points": row["total_points"] or 0,
                    "total_wastes": row["total_wastes"] or 0,
                }
    return None