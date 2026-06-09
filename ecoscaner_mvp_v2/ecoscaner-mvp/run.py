# run.py


import os
import sys
import asyncio
import threading
import logging


# ── Proje kökünü path'e ekle ──────────────────────────────────
ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


from config.settings import DATABASE_PATH, BOT_TOKEN
from database.db import init_db
from services.store_service import seed_default_items


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("run")


# ─────────────────────────────────────────────────────────────
# Başlangıç kontrolleri
# ─────────────────────────────────────────────────────────────


def _preflight():
    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN ayarlanmamış! .env dosyasını kontrol et.")
        sys.exit(1)

    logger.info("📂 DB yolu: %s", DATABASE_PATH)
    init_db(DATABASE_PATH)
    logger.info("✅ Veritabanı hazır")

    seed_default_items()
    logger.info("✅ Mağaza seed tamamlandı")


# ─────────────────────────────────────────────────────────────
# Flask admin — ayrı thread
# ─────────────────────────────────────────────────────────────


def _run_flask():
    from admin.app import app
    app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False)


# ─────────────────────────────────────────────────────────────
# Telegram bot — asyncio
# ─────────────────────────────────────────────────────────────


async def _run_bot():
    from telegram.ext import (
        Application, CommandHandler, MessageHandler,
        filters, CallbackQueryHandler,
    )
    from telegram.request import HTTPXRequest
    from telegram.error import TimedOut, NetworkError

    from handlers.start        import start_command
    from handlers.profile      import profile_command
    from handlers.top          import top_command
    from handlers.help         import help_command
    from handlers.photo        import handle_photo
    from handlers.store        import store_command, buy_command
    from handlers.start_task   import handle_start_task
    from handlers.admin_review import handle_review_callback


    async def error_handler(update, context):
        if isinstance(context.error, (TimedOut, NetworkError)):
            logger.warning("Bağlantı hatası (normal): %s", context.error)
            return
        logger.error("Beklenmeyen hata: %s", context.error, exc_info=context.error)


    request = HTTPXRequest(
        connect_timeout=30, read_timeout=30,
        write_timeout=30,   pool_timeout=30,
    )

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .request(request)
        .build()
    )

    app.add_handler(CommandHandler("start",   start_command))
    app.add_handler(CommandHandler("profile", profile_command))
    app.add_handler(CommandHandler("top",     top_command))
    app.add_handler(CommandHandler("help",    help_command))
    app.add_handler(CommandHandler("store",   store_command))
    app.add_handler(CommandHandler("buy",     buy_command))
    app.add_handler(CommandHandler("scan",    handle_start_task))

    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    # ── YENİ pattern — admin_review.py ile eşleşir ───────────
    app.add_handler(CallbackQueryHandler(
        handle_review_callback,
        pattern=r'^\{"a": "r'
    ))

    app.add_error_handler(error_handler)

    async with app:
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        logger.info("🤖 Bot aktif — bekleniyor...")
        await asyncio.Event().wait()


# ─────────────────────────────────────────────────────────────
# Ana giriş
# ─────────────────────────────────────────────────────────────


if __name__ == "__main__":
    sep = "=" * 40
    print(sep)
    print("EcoScaner MVP - baslatiliyor")
    print(sep)

    _preflight()

    flask_thread = threading.Thread(target=_run_flask, daemon=True)
    flask_thread.start()
    logger.info("✅ Admin panel → http://127.0.0.1:5000")
    logger.info("✅ Mobil web app → http://127.0.0.1:5000/app")

    print(sep)
    print("Bot aktif")
    print("Admin panel -> http://127.0.0.1:5000")
    print("Mobil uygulama -> http://127.0.0.1:5000/app")
    print("Durdurmak icin -> CTRL+C")
    print(sep)

    try:
        asyncio.run(_run_bot())
    except KeyboardInterrupt:
        logger.info("🛑 Bot durduruldu.")
