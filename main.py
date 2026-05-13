from __future__ import annotations

import logging

from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler

from bot.handlers import cmd_start, cmd_status, cmd_report, cmd_fetch, cmd_fetch_wb, handle_callback
from config import BOT_TOKEN, validate_config
from db.database import init_db
from scheduler.jobs import setup_scheduler

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def main() -> None:
    validate_config()
    init_db()

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("report", cmd_report))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("fetch", cmd_fetch))
    app.add_handler(CommandHandler("fetch_wb", cmd_fetch_wb))
    app.add_handler(CallbackQueryHandler(handle_callback))

    setup_scheduler(app)
    logger.info("Bot started")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
