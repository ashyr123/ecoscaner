# api/app_routes.py — Mobil web app JSON API (Faz 2–4)

import os

from flask import Blueprint, jsonify, request, make_response

from config.settings import GEMINI_API_KEY, WEBAPP_URL
from services.app_api_service import (
    get_profile,
    get_user_activity,
    get_leaderboard_data,
    get_store_data,
)
from services.telegram_webapp import validate_init_data
from services.web_auth import (
    SESSION_COOKIE,
    SESSION_MAX_AGE,
    create_session_token,
    get_authenticated_user_id,
    login_required_api,
)
from services.user_service import get_or_create_user
from services.store_service import buy_item
from services.scan_service import process_photo_scan

app_api_bp = Blueprint("app_api", __name__, url_prefix="/api/app")


def _set_session_cookie(response, telegram_id: int):
    token = create_session_token(telegram_id)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="Lax",
        secure=os.getenv("WEBAPP_COOKIE_SECURE", "").lower() in ("1", "true"),
    )
    return response


@app_api_bp.route("/config")
def api_config():
    dev_user = os.getenv("APP_DEV_USER_ID", "").strip()
    allow_dev = os.getenv("APP_ALLOW_DEV_AUTH", "").lower() in ("1", "true", "yes")
    return jsonify({
        "webappUrl": WEBAPP_URL,
        "hasGeminiChat": bool(GEMINI_API_KEY),
        "devUserId": int(dev_user) if dev_user.isdigit() else None,
        "allowDevAuth": allow_dev,
        "authenticated": get_authenticated_user_id() is not None,
    })


@app_api_bp.route("/auth", methods=["POST"])
def api_auth():
    data = request.get_json(silent=True) or {}
    init_data = data.get("initData") or data.get("init_data") or ""

    user = validate_init_data(init_data)
    if not user:
        return jsonify({
            "ok": False,
            "error": "Geçersiz Telegram oturumu. Uygulamayı Telegram içinden açın.",
        }), 401

    tid = int(user["id"])
    get_or_create_user(
        tid,
        user.get("username") or "",
        user.get("first_name") or "",
    )

    resp = make_response(jsonify({
        "ok": True,
        "userId": tid,
        "firstName": user.get("first_name") or "Eco-Hero",
        "username": user.get("username") or "",
    }))
    return _set_session_cookie(resp, tid)


@app_api_bp.route("/auth/dev", methods=["POST"])
def api_auth_dev():
    if os.getenv("APP_ALLOW_DEV_AUTH", "").lower() not in ("1", "true", "yes"):
        return jsonify({"ok": False, "error": "Dev auth disabled"}), 403

    data = request.get_json(silent=True) or {}
    raw = str(data.get("userId") or data.get("user_id") or "").strip()
    if not raw.isdigit():
        return jsonify({"ok": False, "error": "userId required"}), 400

    tid = int(raw)
    get_or_create_user(tid, "dev", "Dev User")
    resp = make_response(jsonify({"ok": True, "userId": tid}))
    return _set_session_cookie(resp, tid)


@app_api_bp.route("/profile")
@login_required_api
def api_profile():
    tid = request.telegram_id  # type: ignore[attr-defined]
    return jsonify({"profile": get_profile(tid), "userId": tid})


@app_api_bp.route("/activity")
@login_required_api
def api_activity():
    tid = request.telegram_id  # type: ignore[attr-defined]
    limit = min(int(request.args.get("limit", 20)), 50)
    return jsonify({
        "activity": get_user_activity(tid, limit=limit),
        "userId": tid,
    })


@app_api_bp.route("/leaderboard")
@login_required_api
def api_leaderboard():
    tid = request.telegram_id  # type: ignore[attr-defined]
    limit = min(int(request.args.get("limit", 100)), 100)
    return jsonify({
        "leaderboard": get_leaderboard_data(tid, limit=limit),
        "userId": tid,
    })


@app_api_bp.route("/store")
@login_required_api
def api_store():
    tid = request.telegram_id  # type: ignore[attr-defined]
    return jsonify({"store": get_store_data(tid), "userId": tid})


@app_api_bp.route("/store/buy", methods=["POST"])
@login_required_api
def api_store_buy():
    tid = request.telegram_id  # type: ignore[attr-defined]
    data = request.get_json(silent=True) or {}
    try:
        item_id = int(data.get("itemId") or data.get("item_id"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "itemId required"}), 400

    ok, msg = buy_item(tid, item_id)
    store = get_store_data(tid)
    profile = get_profile(tid)
    return jsonify({
        "ok": ok,
        "message": msg.replace("<b>", "").replace("</b>", "").replace("<code>", "").replace("</code>", ""),
        "store": store,
        "profile": profile,
    }), (200 if ok else 400)


@app_api_bp.route("/scan", methods=["POST"])
@login_required_api
def api_scan():
    tid = request.telegram_id  # type: ignore[attr-defined]

    if "image" not in request.files:
        return jsonify({"ok": False, "error": "image file required"}), 400

    file = request.files["image"]
    photo_bytes = file.read()
    if not photo_bytes or len(photo_bytes) < 1000:
        return jsonify({"ok": False, "error": "Invalid or empty image"}), 400
    if len(photo_bytes) > 8 * 1024 * 1024:
        return jsonify({"ok": False, "error": "Image too large (max 8MB)"}), 400

    result = process_photo_scan(tid, photo_bytes, source="web", skip_token_check=True)
    status_code = 200 if result.get("ok") else (
        202 if result.get("status") == "review" else 400
    )
    return jsonify(result), status_code


@app_api_bp.route("/chat", methods=["POST"])
@login_required_api
def api_chat():
    if not GEMINI_API_KEY:
        return jsonify({"ok": False, "error": "Chat not configured"}), 503

    import httpx

    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"ok": False, "error": "message required"}), 400

    tid = request.telegram_id  # type: ignore[attr-defined]
    profile = get_profile(tid)
    lang = data.get("language") or "ru"

    system = (
        f"You are Eco-Assistant in EcoScaner app. User has {profile.get('totalPoints', 0)} points. "
        f"Reply in language: {lang}. Max 3 sentences. Cheerful, recycling focus."
    )

    try:
        with httpx.Client(timeout=30) as client:
            resp = client.post(
                "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent",
                params={"key": GEMINI_API_KEY},
                json={
                    "contents": [{"role": "user", "parts": [{"text": message}]}],
                    "systemInstruction": {"parts": [{"text": system}]},
                },
                
            )
            resp.raise_for_status()
            body = resp.json()
            reply = body["candidates"][0]["content"]["parts"][0]["text"]
            return jsonify({"ok": True, "reply": reply})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 502
