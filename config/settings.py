# config/settings.py

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────────────────────
# Yollar
# ─────────────────────────────────────────────────────────────

BASE_DIR      = Path(__file__).resolve().parent.parent
DATABASE_PATH = os.getenv("DATABASE_PATH", str(BASE_DIR / "ecoscaner.db"))

# ─────────────────────────────────────────────────────────────
# Telegram
# ─────────────────────────────────────────────────────────────

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")

ADMIN_TELEGRAM_IDS: list[int] = [
    int(x.strip())
    for x in os.getenv("ADMIN_TELEGRAM_IDS", "").split(",")
    if x.strip().isdigit()
]

# ─────────────────────────────────────────────────────────────
# OpenRouter / AI
# ─────────────────────────────────────────────────────────────

OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL:   str = os.getenv("OPENROUTER_MODEL", "google/gemini-flash-1.5")

# ─────────────────────────────────────────────────────────────
# Flask admin panel
# ─────────────────────────────────────────────────────────────

ADMIN_SECRET:   str = os.getenv("ADMIN_SECRET", "")
ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "")

# ─────────────────────────────────────────────────────────────
# Oyun mekanikleri
# ─────────────────────────────────────────────────────────────

POINTS_PER_BOTTLE: int = int(os.getenv("POINTS_PER_BOTTLE", "5"))
DAILY_LIMIT:       int = int(os.getenv("DAILY_LIMIT", "10"))
# config/settings.py
CATEGORY_DAY_LIMIT: int = int(os.getenv("CATEGORY_DAY_LIMIT", "4"))

# ─────────────────────────────────────────────────────────────
# Fraud koruması
# ─────────────────────────────────────────────────────────────

ACCOUNT_MIN_AGE_DAYS:      int   = int(os.getenv("ACCOUNT_MIN_AGE_DAYS", "0"))
FRAUD_SCORE_THRESHOLD:     float = float(os.getenv("FRAUD_SCORE_THRESHOLD", "0.65"))
PHASH_DUPLICATE_THRESHOLD: int   = int(os.getenv("PHASH_DUPLICATE_THRESHOLD", "10"))

# ─────────────────────────────────────────────────────────────
# Doğrulama — eksik varsa hemen çök
# ─────────────────────────────────────────────────────────────

_missing = [
    name for name, val in [
        ("BOT_TOKEN",          BOT_TOKEN),
        ("OPENROUTER_API_KEY", OPENROUTER_API_KEY),
        ("ADMIN_SECRET",       ADMIN_SECRET),
        ("ADMIN_PASSWORD",     ADMIN_PASSWORD),
    ]
    if not val
]

if not ADMIN_TELEGRAM_IDS:
    _missing.append("ADMIN_TELEGRAM_IDS")

if _missing:
    raise ValueError(
        f".env dosyasında eksik değişkenler: {', '.join(_missing)}\n"
        f"Dosya konumu: {BASE_DIR / '.env'}"
    )