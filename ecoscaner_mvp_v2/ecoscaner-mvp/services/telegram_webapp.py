# services/telegram_webapp.py — Telegram Mini App initData doğrulama

from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

from config.settings import BOT_TOKEN


def validate_init_data(init_data: str, max_age_sec: int = 86400) -> dict | None:
    """
    Telegram WebApp initData HMAC doğrulaması.
    Başarılıysa kullanıcı dict döner; aksi halde None.
    """
    if not init_data or not BOT_TOKEN:
        return None

    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    except Exception:
        return None

    received_hash = pairs.pop("hash", None)
    if not received_hash:
        return None

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))

    secret_key = hmac.new(
        b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256
    ).digest()
    computed = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(computed, received_hash):
        return None

    auth_date = int(pairs.get("auth_date", "0") or 0)
    if auth_date and (time.time() - auth_date) > max_age_sec:
        return None

    user_raw = pairs.get("user")
    if not user_raw:
        return None

    try:
        user = json.loads(user_raw)
    except json.JSONDecodeError:
        return None

    if not user.get("id"):
        return None

    return user
