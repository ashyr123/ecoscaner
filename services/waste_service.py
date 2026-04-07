# services/waste_service.py — EcoScaner

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import Optional

from database.db import get_connection


# ─────────────────────────────────────────────────────────────
# Puan tablosu
# ─────────────────────────────────────────────────────────────

CATEGORY_POINTS: dict[str, int] = {
    "plastic":   5,
    "glass":     8,
    "cardboard": 3,
    "metal":     6,
}


def get_points_for_category(category: str, is_empty: bool) -> int:
    base = CATEGORY_POINTS.get((category or "").strip().lower(), 2)
    return base if is_empty else max(1, base // 2)


# ─────────────────────────────────────────────────────────────
# DB bağlantı yöneticisi
# ─────────────────────────────────────────────────────────────

@contextlib.contextmanager
def _db():
    with get_connection() as conn:
        yield conn.cursor(), conn


# ─────────────────────────────────────────────────────────────
# Veri modeli
# ─────────────────────────────────────────────────────────────

@dataclass
class WasteRecord:
    telegram_id: int
    image_hash:  str
    phash:       str   = ""
    file_id:     str   = ""
    points:      int   = 5
    brand:       str   = "UNKNOWN"
    fingerprint: str   = ""
    category:    str   = ""
    is_empty:    bool  = True
    is_damaged:  bool  = False
    raw_volume:  str   = ""
    raw_color:   str   = ""
    fraud_score: float = 0.0
    event_proof: str   = ""
    gps_lat:     float | None = None
    gps_lon:     float | None = None

    def __post_init__(self) -> None:
        if not self.phash:
            self.phash = self.image_hash
        if not self.fingerprint:
            self.fingerprint = self.image_hash


def add_waste(rec: WasteRecord) -> None:
    with _db() as (c, conn):
        c.execute(
            """
            INSERT INTO wastes (
                telegram_id, image_hash, phash, file_id,
                points, brand, fingerprint,
                category, is_empty, is_damaged,
                raw_volume, raw_color,
                fraud_score, event_proof,
                gps_lat, gps_lon
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rec.telegram_id, rec.image_hash, rec.phash, rec.file_id,
                rec.points, rec.brand, rec.fingerprint,
                rec.category,
                1 if rec.is_empty   else 0,
                1 if rec.is_damaged else 0,
                rec.raw_volume, rec.raw_color,
                rec.fraud_score, rec.event_proof,
                rec.gps_lat, rec.gps_lon,
            ),
        )
        c.execute(
            """
            UPDATE users
            SET total_points        = total_points + ?,
                total_earned_points = total_earned_points + ?,
                total_wastes        = total_wastes + 1
            WHERE telegram_id = ?
            """,
            (rec.points, rec.points, rec.telegram_id),
        )
        conn.commit()


# ─────────────────────────────────────────────────────────────
# Fingerprint yardımcısı — admin_review.py için
# ─────────────────────────────────────────────────────────────

def build_fingerprint_from_ai(brand: str, volume: str, color: str) -> str:
    """Admin review'dan kabul edilen fotoğraflar için fingerprint üret."""
    from services.fingerprint import build_fingerprint
    return build_fingerprint(brand=brand, volume=volume, color=color)


# ─────────────────────────────────────────────────────────────
# Duplicate kontrolleri
# ─────────────────────────────────────────────────────────────

def photo_hash_exists(image_hash: str) -> bool:
    with _db() as (c, _):
        c.execute("SELECT 1 FROM wastes WHERE image_hash = ? LIMIT 1", (image_hash,))
        return c.fetchone() is not None


def file_id_exists(file_id: str) -> bool:
    if not file_id:
        return False
    with _db() as (c, _):
        c.execute("SELECT 1 FROM wastes WHERE file_id = ? LIMIT 1", (file_id,))
        return c.fetchone() is not None


def fingerprint_exists(telegram_id: int, fingerprint: str) -> bool:
    with _db() as (c, _):
        c.execute(
            """
            SELECT 1 FROM wastes
            WHERE telegram_id = ?
              AND fingerprint  = ?
              AND DATE(created_at) = DATE('now')
            LIMIT 1
            """,
            (telegram_id, fingerprint),
        )
        return c.fetchone() is not None


# ─────────────────────────────────────────────────────────────
# Perceptual hash listesi
# ─────────────────────────────────────────────────────────────

def get_user_phashes(telegram_id: int, limit: int = 100) -> list[str]:
    with _db() as (c, _):
        c.execute(
            """
            SELECT phash FROM wastes
            WHERE telegram_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (telegram_id, limit),
        )
        return [row[0] for row in c.fetchall() if row[0]]


# ─────────────────────────────────────────────────────────────
# Sayaçlar
# ─────────────────────────────────────────────────────────────

def get_user_daily_count(telegram_id: int) -> int:
    with _db() as (c, _):
        c.execute(
            "SELECT COUNT(*) FROM wastes WHERE telegram_id = ? AND DATE(created_at) = DATE('now')",
            (telegram_id,),
        )
        return c.fetchone()[0] or 0


def get_category_daily_count(telegram_id: int, category: str) -> int:
    with _db() as (c, _):
        c.execute(
            """
            SELECT COUNT(*) FROM wastes
            WHERE telegram_id = ?
              AND LOWER(category) = LOWER(?)
              AND DATE(created_at) = DATE('now')
            """,
            (telegram_id, category),
        )
        return c.fetchone()[0] or 0