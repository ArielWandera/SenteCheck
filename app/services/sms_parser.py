"""
sms_parser.py — Parses raw MTN Uganda and Airtel Uganda SMS strings.

Uses named-group regex patterns to extract amount, merchant, and balance.
Returns a ParsedSMS dataclass. Never raises — returns is_mobile_money=False
or direction=None on unrecognised input.
"""
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


@dataclass
class ParsedSMS:
    is_mobile_money: bool
    direction: str | None  # "out" or "in"
    amount: Decimal | None
    merchant_name: str | None  # recipient (out) or sender (in)
    balance: Decimal | None
    sim: str | None  # "MTN" or "Airtel"
    raw: str  # original SMS, never modified


def _to_decimal(raw: str) -> Decimal | None:
    """Convert '10,000' or '10,000.50' to Decimal. Returns None on failure."""
    try:
        return Decimal(raw.replace(",", ""))
    except (InvalidOperation, AttributeError):
        return None


# ---------------------------------------------------------------------------
# Regex patterns — each is (sim_label, direction, compiled_pattern).
# Named groups:  amount (required), merchant (optional), balance (optional).
# ---------------------------------------------------------------------------
_PATTERNS: list[tuple[str, str, re.Pattern]] = [
    # ── MTN ─────────────────────────────────────────────────────────────────
    #
    # Outgoing payment:
    # "You have sent UGX 10,000 to PEGASUS. Your new balance is UGX 45,000.
    #  Transaction ID: ABC123"
    (
        "MTN",
        "out",
        re.compile(
            r"you have sent UGX\s+(?P<amount>[\d,]+(?:\.\d+)?)"
            r"\s+to\s+(?P<merchant>.+?)\."
            r".*?new balance is UGX\s+(?P<balance>[\d,]+(?:\.\d+)?)",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    # Incoming deposit:
    # "You have received UGX 47,000 from PEGASUS PAYOUTS.
    #  Your new balance is UGX 92,000."
    (
        "MTN",
        "in",
        re.compile(
            r"you have received UGX\s+(?P<amount>[\d,]+(?:\.\d+)?)"
            r"\s+from\s+(?P<merchant>.+?)\."
            r".*?new balance is UGX\s+(?P<balance>[\d,]+(?:\.\d+)?)",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    # Cash withdrawal (money leaving MTN wallet at an agent):
    # "Your withdrawal of UGX 20,000 was successful.
    #  Your new balance is UGX 25,000."
    (
        "MTN",
        "out",
        re.compile(
            r"your withdrawal of UGX\s+(?P<amount>[\d,]+(?:\.\d+)?)"
            r"\s+was successful\."
            r".*?new balance is UGX\s+(?P<balance>[\d,]+(?:\.\d+)?)",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    # ── Airtel ───────────────────────────────────────────────────────────────
    #
    # Outgoing payment:
    # "UGX 10,000 sent to SAINTS BETTING successfully.
    #  Airtel Money Balance: UGX 35,000"
    (
        "Airtel",
        "out",
        re.compile(
            r"UGX\s+(?P<amount>[\d,]+(?:\.\d+)?)"
            r"\s+sent to\s+(?P<merchant>.+?)\s+successfully\."
            r".*?Airtel Money Balance:\s*UGX\s+(?P<balance>[\d,]+(?:\.\d+)?)",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    # Incoming deposit:
    # "You have received UGX 50,000 on your Airtel Money account from SAINTS PAYOUTS."
    (
        "Airtel",
        "in",
        re.compile(
            r"you have received UGX\s+(?P<amount>[\d,]+(?:\.\d+)?)"
            r"\s+on your Airtel Money account from\s+(?P<merchant>.+?)\.",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
]

# Pre-filter: SMS must contain at least one of these keywords (case-insensitive)
# to be worth running regexes against.
_KEYWORDS = [
    "UGX",
    "MTN Mobile Money",
    "Airtel Money",
    "new balance",
    "you have sent",
    "you have received",
    "your withdrawal",
]


def parse_sms(body: str, sim_hint: str | None = None) -> ParsedSMS:
    """
    Parse a raw SMS body.

    Args:
        body:     Raw SMS text as received on the device.
        sim_hint: "MTN" or "Airtel" if known from the SIM slot (optional).
                  Used as a tiebreaker and stored in the result even when
                  the regex already identifies the network.

    Returns:
        ParsedSMS — always succeeds, never raises.
    """
    body_upper = body.upper()
    is_mm = any(kw.upper() in body_upper for kw in _KEYWORDS)

    if not is_mm:
        return ParsedSMS(
            is_mobile_money=False,
            direction=None,
            amount=None,
            merchant_name=None,
            balance=None,
            sim=sim_hint,
            raw=body,
        )

    for sim_label, direction, pattern in _PATTERNS:
        match = pattern.search(body)
        if not match:
            continue

        groups = match.groupdict()
        raw_merchant = groups.get("merchant")
        merchant = raw_merchant.strip() if raw_merchant else None

        return ParsedSMS(
            is_mobile_money=True,
            direction=direction,
            amount=_to_decimal(groups["amount"]),
            merchant_name=merchant or None,
            balance=_to_decimal(groups["balance"]) if groups.get("balance") else None,
            sim=sim_hint or sim_label,
            raw=body,
        )

    # Keywords matched but no pattern did — unknown format, still mobile money.
    return ParsedSMS(
        is_mobile_money=True,
        direction=None,
        amount=None,
        merchant_name=None,
        balance=None,
        sim=sim_hint,
        raw=body,
    )
