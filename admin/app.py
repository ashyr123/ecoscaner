# admin/app.py

import os
import json
import sqlite3
import contextlib
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, render_template, redirect, url_for, session, request
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

_secret   = os.getenv("ADMIN_SECRET")
_password = os.getenv("ADMIN_PASSWORD")

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


@contextlib.contextmanager
def _db():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn.cursor()
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


def get_stats() -> dict:
    with _db() as c:
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
    with _db() as c:
        if search:
            c.execute("""
                SELECT telegram_id, first_name, username,
                       total_points, total_earned_points, total_wastes, created_at
                FROM users
                WHERE first_name LIKE ? OR username LIKE ?
                ORDER BY total_earned_points DESC
            """, (f"%{search}%", f"%{search}%"))
        else:
            c.execute("""
                SELECT telegram_id, first_name, username,
                       total_points, total_earned_points, total_wastes, created_at
                FROM users
                ORDER BY total_earned_points DESC
            """)
        return [dict(r) for r in c.fetchall()]


def get_recent_activity(limit: int = 50) -> list[dict]:
    with _db() as c:
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
    with _db() as c:
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


# ── YENİ: Review queue ───────────────────────────────────────

def get_pending_reviews() -> list[dict]:
    with _db() as c:
        c.execute("""
            SELECT r.id, r.telegram_id, r.phash,
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


def resolve_review(review_id: int) -> None:
    conn = sqlite3.connect(DATABASE_PATH)
    conn.execute("UPDATE review_queue SET resolved = 1 WHERE id = ?", (review_id,))
    conn.commit()
    conn.close()


# ─────────────────────────────────────────────────────────────
# Route'lar
# ─────────────────────────────────────────────────────────────

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
            error = f"Yanlış şifre. {max(remaining, 0)} deneme hakkı kaldı."
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


# ── YENİ: Review queue sayfası ───────────────────────────────

@app.route("/reviews")
@login_required
def reviews():
    return render_template("reviews.html", reviews=get_pending_reviews())


@app.route("/reviews/resolve/<int:review_id>", methods=["POST"])
@login_required
def resolve(review_id: int):
    resolve_review(review_id)
    return redirect(url_for("reviews"))


if __name__ == "__main__":
    app.run(debug=False, host="127.0.0.1", port=5000)