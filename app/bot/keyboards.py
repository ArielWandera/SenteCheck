"""
keyboards.py — Inline keyboard builders for every bot prompt.
"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def consent_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ I Agree — Let's go", callback_data="consent:agree"),
            InlineKeyboardButton("❌ I Do Not Agree", callback_data="consent:disagree"),
        ]
    ])


def deposit_classification_keyboard(transaction_id: int) -> InlineKeyboardMarkup:
    """
    Shown when an unknown outgoing merchant is encountered.
    Callback data carries the transaction ID so the handler can update it.
    """
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "✅ Yes, bet deposit",
                callback_data=f"classify:{transaction_id}:bet_deposit",
            ),
            InlineKeyboardButton(
                "❌ No, other payment",
                callback_data=f"classify:{transaction_id}:other_payment",
            ),
        ]
    ])


def withdrawal_classification_keyboard(transaction_id: int) -> InlineKeyboardMarkup:
    """
    Shown when an unknown incoming merchant is encountered.
    """
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "✅ Yes, bet withdrawal",
                callback_data=f"classify:{transaction_id}:bet_withdrawal",
            ),
            InlineKeyboardButton(
                "❌ No, other income",
                callback_data=f"classify:{transaction_id}:other_income",
            ),
        ]
    ])


def delete_confirm_keyboard() -> InlineKeyboardMarkup:
    """Confirmation keyboard for /deleteaccount. Shown before any data is touched."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🗑️ Yes, delete everything", callback_data="delete:confirm"
            ),
            InlineKeyboardButton("❌ Cancel", callback_data="delete:cancel"),
        ]
    ])
