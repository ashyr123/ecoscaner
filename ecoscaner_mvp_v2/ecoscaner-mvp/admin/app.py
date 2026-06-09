# admin/app.py

import hashlib
import os
import json
import sqlite3
import contextlib
import urllib.request
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, render_template, redirect, url_for, session, request, send_from_directory, jsonify
from dotenv import load_dotenv

from api.app_routes import app_api_bp

load_dotenv()

app = Flask(__name__)
app.register_blueprint(app_api_bp)

_secret   = os.getenv("ADMIN_SECRET")
_password = os.getenv("ADMIN_PASSWORD")
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not _secret or not _password:
    raise RuntimeError("ADMIN_SECRET ve ADMIN_PASSWORD zorunludur.")

app.secret_key = _secret
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
)

ADMIN_PASSWORD = _password

_login_attempts: dict[str, list[datetime]] = {}
MAX_ATTEMPTS   = 5
LOCKOUT_WINDOW = timedelta(minutes=15)

BASE_DIR      = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATABASE_PATH = os.path.join(BASE_DIR, "ecoscaner.db")
WEB_DIR       = os.path.join(BASE_DIR, "web")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

CATEGORY_POINTS = {"plastic": 5, "glass": 8, "cardboard": 3, "metal": 6}
CAT_EMOJI       = {"plastic": "🧴", "metal": "🥫", "glass": "🍶", "cardboard": "📦"}
CAT_RU          = {"plastic": "Пластик", "metal": "Металл", "glass": "Стекло", "cardboard": "Картон"}


@contextlib.contextmanager
def _db():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn.cursor(), conn
    finally:
        conn.close()


def _is_locked_out(ip: str) -> bool:
    now = datetime.utcnow()
    attempts = [t for t in _login_attempts.get(ip, []) if now - t < LOCKOUT_WINDOW]
    _login_attempts[ip] = attempts
    return len(attempts) >= MAX_ATTEMPTS


def _record_attempt(ip: str) -> None:
    _login_attempts.setdefault(ip, []).append(datetime.utcnow())


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def _tg_send(chat_id: int, text: str) -> None:
    if not BOT_TOKEN or not chat_id:
        return
    try:
        payload = json.dumps({
            "chat_id":    chat_id,
            "text":       text,
            "parse_mode": "HTML",
        }).encode()
        req = urllib.request.Request(
            "https://api.telegram.org/bot" + BOT_TOKEN + "/sendMessage",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass


def get_stats() -> dict:
    with _db() as (c, _):
        c.execute("""
            SELECT
                (SELECT COUNT(*) FROM users)                                        AS total_users,
                (SELECT COUNT(*) FROM wastes)                                       AS total_bottles,
                (SELECT COALESCE(SUM(total_points), 0) FROM users)                  AS total_points,
                (SELECT COUNT(*) FROM wastes  WHERE DATE(created_at) = DATE('now')) AS today_bottles,
                (SELECT COUNT(*) FROM users   WHERE DATE(created_at) = DATE('now')) AS today_users,
                (SELECT COUNT(*) FROM review_queue WHERE resolved = 0)              AS pending_reviews
        """)
        return dict(c.fetchone())


def get_users(search: str = "") -> list[dict]:
    with _db() as (c, _):
        if search:
            c.execute("""
                SELECT telegram_id, first_name, username,
                       total_points, total_earned_points, total_wastes, created_at
                FROM users
                WHERE first_name LIKE ? OR username LIKE ?
                ORDER BY total_earned_points DESC
            """, ("%" + search + "%", "%" + search + "%"))
        else:
            c.execute("""
                SELECT telegram_id, first_name, username,
                       total_points, total_earned_points, total_wastes, created_at
                FROM users
                ORDER BY total_earned_points DESC
            """)
        return [dict(r) for r in c.fetchall()]


def get_recent_activity(limit: int = 50) -> list[dict]:
    with _db() as (c, _):
        c.execute("""
            SELECT w.id, u.first_name, u.username,
                   w.brand, w.category, w.points,
                   w.fraud_score, w.created_at
            FROM wastes w
            JOIN users u ON w.telegram_id = u.telegram_id
            ORDER BY w.created_at DESC
            LIMIT ?
        """, (limit,))
        return [dict(r) for r in c.fetchall()]


def get_daily_chart() -> tuple[list[str], list[int]]:
    with _db() as (c, _):
        c.execute("""
            SELECT DATE(created_at) AS day, COUNT(*) AS cnt
            FROM wastes
            WHERE created_at >= DATE('now', '-6 days')
            GROUP BY day
            ORDER BY day
        """)
        rows = {r["day"]: r["cnt"] for r in c.fetchall()}
    today = datetime.utcnow().date()
    days  = [(today - timedelta(days=i)) for i in range(6, -1, -1)]
    return (
        [d.strftime("%d.%m") for d in days],
        [rows.get(d.strftime("%Y-%m-%d"), 0) for d in days],
    )


def get_pending_reviews() -> list[dict]:
    with _db() as (c, _):
        c.execute("""
            SELECT r.id, r.telegram_id, r.phash, r.file_id,
                   r.result_a, r.result_b, r.created_at,
                   u.first_name, u.username
            FROM review_queue r
            LEFT JOIN users u ON r.telegram_id = u.telegram_id
            WHERE r.resolved = 0
            ORDER BY r.created_at DESC
        """)
        rows = []
        for row in c.fetchall():
            d = dict(row)
            try: d["result_a"] = json.loads(d["result_a"])
            except: d["result_a"] = {}
            try: d["result_b"] = json.loads(d["result_b"])
            except: d["result_b"] = {}
            rows.append(d)
        return rows


def _resolve_and_save(review_id: int, category: str) -> dict | None:
    with _db() as (c, conn):
        c.execute("""
            SELECT r.telegram_id, r.phash, r.file_id, r.result_a, r.result_b
            FROM review_queue r
            WHERE r.id = ? AND r.resolved = 0
        """, (review_id,))
        row = c.fetchone()
        if not row:
            return None

        telegram_id = row["telegram_id"]
        phash       = row["phash"] or ""
        file_id     = row["file_id"] or ""

        try:
            result_a = json.loads(row["result_a"])
        except Exception:
            result_a = {}

        conn.execute(
            "UPDATE review_queue SET resolved = 1 WHERE id = ?",
            (review_id,),
        )

        if category != "reject":
            is_empty = result_a.get("is_empty", True)
            points   = CATEGORY_POINTS.get(category, 3)
            if not is_empty:
                points = max(1, points // 2)

            brand     = result_a.get("brand", "UNKNOWN")
            fake_hash = hashlib.sha256(
                ("review_" + str(review_id) + "_" + str(telegram_id)).encode()
            ).hexdigest()

            conn.execute("""
                INSERT INTO wastes (
                    telegram_id, image_hash, phash, file_id,
                    points, brand, fingerprint,
                    category, is_empty, is_damaged,
                    raw_volume, raw_color,
                    fraud_score, event_proof
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                telegram_id, fake_hash, phash, file_id,
                points, brand, fake_hash,
                category,
                1 if is_empty else 0,
                1 if result_a.get("is_damaged", False) else 0,
                result_a.get("volume", ""),
                result_a.get("color", ""),
                0.0, "admin_panel_approved",
            ))

            conn.execute("""
                UPDATE users
                SET total_points        = total_points + ?,
                    total_earned_points = total_earned_points + ?,
                    total_wastes        = total_wastes + 1
                WHERE telegram_id = ?
            """, (points, points, telegram_id))

            conn.commit()
            return {"telegram_id": telegram_id, "points": points, "category": category}

        conn.commit()
        return {"telegram_id": telegram_id, "points": 0, "category": "reject"}


# ─────────────────────────────────────────────────────────────
# Route'lar
# ─────────────────────────────────────────────────────────────

@app.route("/app")
@app.route("/app/")
def mobile_app():
    return send_from_directory(WEB_DIR, "index.html")


# /api/app/* routes → api.app_routes blueprint (config dahil)


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("logged_in"):
        return redirect(url_for("dashboard"))
    error = None
    ip    = request.remote_addr
    if request.method == "POST":
        if _is_locked_out(ip):
            error = "Çok fazla hatalı giriş. 15 dakika bekle."
        elif request.form.get("password") == ADMIN_PASSWORD:
            session.permanent = True
            session["logged_in"] = True
            _login_attempts.pop(ip, None)
            return redirect(url_for("dashboard"))
        else:
            _record_attempt(ip)
            remaining = MAX_ATTEMPTS - len(_login_attempts.get(ip, []))
            error = "Yanlış şifre. " + str(max(remaining, 0)) + " deneme hakkı kaldı."
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def dashboard():
    labels, data = get_daily_chart()
    return render_template(
        "dashboard.html",
        stats        = get_stats(),
        activity     = get_recent_activity(10),
        chart_labels = json.dumps(labels),
        chart_data   = json.dumps(data),
    )


@app.route("/users")
@login_required
def users():
    search = request.args.get("search", "").strip()
    return render_template("users.html", users=get_users(search), search=search)


@app.route("/activity")
@login_required
def activity():
    return render_template("activity.html", activity=get_recent_activity(50))


@app.route("/reviews")
@login_required
def reviews():
    return render_template("reviews.html", reviews=get_pending_reviews())


@app.route("/reviews/resolve/<int:review_id>", methods=["POST"])
@login_required
def resolve(review_id: int):
    category = request.form.get("category", "reject")
    result   = _resolve_and_save(review_id, category)

    if result and result["telegram_id"]:
        uid = result["telegram_id"]
        if result["category"] == "reject":
            _tg_send(uid,
                "❌ Фото проверено — не принято.\n"
                "Сделай новый снимок и попробуй снова! 📸"
            )
        else:
            emoji  = CAT_EMOJI.get(category, "♻️")
            cat_ru = CAT_RU.get(category, category)
            pts    = result["points"]
            _tg_send(uid,
                "✅ Фото проверено и <b>принято</b>!\n"
                + emoji + " Категория: " + cat_ru + "\n"
                "💎 +" + str(pts) + " баллов зачислено!\n\n"
                "Спасибо! 🌱"
            )

    return redirect(url_for("reviews"))


@app.route("/reviews/photo/<int:review_id>")
@login_required
def review_photo(review_id: int):
    if not BOT_TOKEN:
        return "BOT_TOKEN eksik", 500

    with _db() as (c, _):
        c.execute("SELECT file_id FROM review_queue WHERE id = ?", (review_id,))
        row = c.fetchone()

    if not row or not row["file_id"]:
        return "Fotograf bulunamadi", 404

    try:
        api_url = "https://api.telegram.org/bot" + BOT_TOKEN + "/getFile?file_id=" + row["file_id"]
        with urllib.request.urlopen(api_url, timeout=10) as resp:
            data = json.loads(resp.read())
        file_path = data["result"]["file_path"]
        photo_url = "https://api.telegram.org/file/bot" + BOT_TOKEN + "/" + file_path
        return redirect(photo_url)
    except Exception as e:
        return "Fotograf yuklenemedi: " + str(e), 500


if __name__ == "__main__":
    app.run(debug=False, host="127.0.0.1", port=5000)
