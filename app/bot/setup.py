"""
setup.py — Creates and configures the python-telegram-bot Application.

The Application is built once at module import time (module-level singleton).
app/main.py calls ptb_app.initialize() on startup and ptb_app.shutdown() on
shutdown. The Telegram webhook endpoint in routers/webhook.py feeds updates
into ptb_app.process_update().
"""
from telegram.ext import Application, CallbackQueryHandler, CommandHandler

from app.bot import handlers
from app.config import settings
from app.database import AsyncSessionLocal


def create_application() -> Application:
    application = (
        Application.builder()
        .token(settings.TELEGRAM_BOT_TOKEN)
        .build()
    )

    # Make the DB session factory available to all handlers via bot_data
    application.bot_data["session_factory"] = AsyncSessionLocal

    # ── Command handlers ──────────────────────────────────────────────────
    application.add_handler(CommandHandler("start", handlers.start))
    application.add_handler(CommandHandler("help", handlers.help_command))
    application.add_handler(CommandHandler("summary", handlers.summary))
    application.add_handler(CommandHandler("losses", handlers.losses))
    application.add_handler(CommandHandler("wins", handlers.wins))
    application.add_handler(CommandHandler("history", handlers.history))
    application.add_handler(CommandHandler("bankroll", handlers.bankroll))
    application.add_handler(CommandHandler("bet", handlers.bet))
    application.add_handler(CommandHandler("merchants", handlers.merchants))
    application.add_handler(CommandHandler("addmerchant", handlers.addmerchant))
    application.add_handler(CommandHandler("mydata", handlers.mydata))
    application.add_handler(CommandHandler("deleteaccount", handlers.deleteaccount))

    # ── Callback query handlers ───────────────────────────────────────────
    application.add_handler(
        CallbackQueryHandler(handlers.consent_callback, pattern=r"^consent:")
    )
    application.add_handler(
        CallbackQueryHandler(handlers.classification_callback, pattern=r"^classify:")
    )
    application.add_handler(
        CallbackQueryHandler(handlers.deleteaccount_callback, pattern=r"^delete:")
    )

    return application


ptb_app = create_application()
