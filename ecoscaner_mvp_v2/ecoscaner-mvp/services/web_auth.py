# services/web_auth.py — Mobil web oturum (signed cookie / header)

from __future__ import annotations

import os
from functools import wraps
from typing import Callable

from flask import Request, jsonify, request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from config.settings import ADMIN_SECRET
from services.app_api_service import resolve_telegram_id

SESSION_COOKIE = "ecoscaner_sid"
SESSION_HEADER = "X-App-Session"
SESSION_MAX_AGE = 60 * 60 * 24 * 7  # 7 gün

_serializer = URLSafeTimedSerializer(ADMIN_SECRET, salt="ecoscaner-webapp-v1")


def create_session_token(telegram_id: int) -> str:
    return _serializer.dumps({"telegram_id": telegram_id})


def verify_session_token(token: str) -> int | None:
    try:
        data = _serializer.loads(token, max_age=SESSION_MAX_AGE)
        tid = data.get("telegram_id")
        return int(tid) if tid is not None else None
    except (BadSignature, SignatureExpired, Exception):
        return None


def _token_from_request(req: Request) -> str | None:
    if req.headers.get(SESSION_HEADER):
        return req.headers.get(SESSION_HEADER)
    return req.cookies.get(SESSION_COOKIE)


def get_authenticated_user_id(req: Request | None = None) -> int | None:
    req = req or request
    token = _token_from_request(req)
    if token:
        tid = verify_session_token(token)
        if tid:
            return tid

    if os.getenv("APP_ALLOW_DEV_AUTH", "").lower() in ("1", "true", "yes"):
        raw = req.args.get("user_id", "").strip()
        requested = int(raw) if raw.isdigit() else None
        return resolve_telegram_id(requested)

    return None


def login_required_api(f: Callable):
    @wraps(f)
    def decorated(*args, **kwargs):
        tid = get_authenticated_user_id()
        if tid is None:
            return jsonify({
                "error": "Giriş gerekli. Telegram uygulamasından açın veya oturum süresi dolmuş.",
                "code": "unauthorized",
            }), 401
        request.telegram_id = tid  # type: ignore[attr-defined]
        return f(*args, **kwargs)
    return decorated
