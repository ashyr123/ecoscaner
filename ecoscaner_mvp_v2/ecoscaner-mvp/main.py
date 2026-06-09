# main.py

import asyncio
import logging
import signal
import sys

from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler
from telegram.request import HTTPXRequest
from telegram.error import TimedOut, NetworkError

from config.settings import BOT_TOKEN, DATABASE_PATH
from database.db import init_db
from services.store_service import seed_default_items
from handlers.start        import start_command
from handlers.profile      import profile_command
from handlers.top          import top_command
from handlers.help         import help_command
from handlers.photo        import handle_photo
from handlers.store        import store_command, buy_command
from handlers.admin_review import handle_review_callback
from handlers.start_task   import handle_start_task  # ← YENİ

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


async def error_handler(update, context) -> None:
    if isinstance(context.error, (TimedOut, NetworkError)):
        logger.warning("Bağlantı hatası (normal): %s", context.error)
        return
    logger.error("Beklenmeyen hata: %s", context.error, exc_info=context.error)


async def main() -> None:
    init_db(DATABASE_PATH)
    seed_default_items()
    logger.info("✅ Veritabanı ve mağaza hazır → %s", DATABASE_PATH)

    request = HTTPXRequest(
        connect_timeout=30,
        read_timeout=30,
        write_timeout=30,
        pool_timeout=30,
    )

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .request(request)
        .build()
    )

    app.add_handler(CommandHandler("start",      start_command))
    app.add_handler(CommandHandler("profile",    profile_command))
    app.add_handler(CommandHandler("top",        top_command))
    app.add_handler(CommandHandler("help",       help_command))
    app.add_handler(CommandHandler("store",      store_command))
    app.add_handler(CommandHandler("buy",        buy_command))
    app.add_handler(CommandHandler("start_task", handle_start_task))  # ← YENİ
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    # YENİ — admin_review.py ile eşleşir
    app.add_handler(CallbackQueryHandler(
        handle_review_callback,
        pattern=r'^\{"a": "r'
    ))
    app.add_error_handler(error_handler)

    stop_event = asyncio.Event()

    def _on_stop():
        logger.info("🛑 Durdurma sinyali alındı...")
        stop_event.set()

    if sys.platform != "win32":
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, _on_stop)

    logger.info("🚀 EcoScaner başlatılıyor...")

    async with app:
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        logger.info("🤖 Bot aktif — bekleniyor...")

        try:
            await stop_event.wait()
        except asyncio.CancelledError:
            pass

        logger.info("🔄 Kapatılıyor...")
        await app.updater.stop()
        await app.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 Bot durduruldu.")