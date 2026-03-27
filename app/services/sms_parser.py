"""
sms_parser.py — Parses raw MTN Uganda and Airtel Uganda SMS strings.

Uses named-group regex patterns to extract amount, merchant, and balance.
Returns a ParsedSMS dataclass. Never raises — returns is_mobile_money=False
or direction=None on unrecognised input.

Patterns are derived from real SMS samples collected in Uganda (March 2026).
Add new patterns below as new formats are encountered in production.
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
#
# Real SMS samples (Uganda, March 2026):
#
# MTN out person:    "Y'ello. You have sent UGX 2,000 to 256750066399, ESTELLA,WANDERA.
#                     Fee:UGX 100.00. Transaction ID:... Your Mobile Money balance is now UGX 45,845.62."
# MTN out business:  "Y'ello. ELIA INVESTMENTS LIMITED has deducted UGX 10000 at a fee of UGX 550
#                     Transaction ID: ... New balance is:UGX 4946."
# MTN out withdraw:  "You have withdrawn UGX 25,000 on 2026-03-25 11:51:59. Fee: UGX 880, Tax: UGX 125.
#                     New balance: UGX 28,945.62."
# MTN in  business:  "You have deposited UGX 650000 from ELIA INVESTMENTS LIMITED on 2026-02-20 11:34:15.
#                     New balance: UGX 786818."
# MTN in  cross-net: "You have received UGX 40000 from Airtel Money on 2026-03-27 23:06:11. fee:0.
#                     Reason: ESTELLA WANDERA , 0750066399. New balance: UGX 47946."
#
# Airtel in  deposit: "CASH DEPOSIT of UGX 2,000 from  MTN MOBILE MONEY UGANDA LTD.
#                      Bal UGX 278,767. TID 143779280993."
# Airtel out person:  "SENT UGX 40,000 to ARIEL EMMANUEL WANDERA on 256778556703.
#                      Fee UGX 500.0 Bal UGX 276,767."  ← also covers business sends
# Airtel out withdraw:"WITHDRAWN. TID 142289013602. UGX25,000 with Agent ID: 234328.
#                      Fee UGX 880.Tax UGX 125.Bal UGX 458,402."
# ---------------------------------------------------------------------------
_PATTERNS: list[tuple[str, str, re.Pattern]] = [

    # ── MTN — outgoing person-to-person ─────────────────────────────────────
    # "You have sent UGX 2,000 to 256750066399, ESTELLA,WANDERA.
    #  ... Your Mobile Money balance is now UGX 45,845.62."
    (
        "MTN",
        "out",
        re.compile(
            r"you have sent UGX\s+(?P<amount>[\d,]+(?:\.\d+)?)"
            r"\s+to\s+\d+,\s*(?P<merchant>[^.]+?)\."
            r".*?balance is now UGX\s+(?P<balance>[\d,]+(?:\.\d+)?)",
            re.IGNORECASE | re.DOTALL,
        ),
    ),

    # ── MTN — outgoing business deduction ───────────────────────────────────
    # "ELIA INVESTMENTS LIMITED has deducted UGX 10000 at a fee of UGX 550
    #  ... New balance is:UGX 4946."
    (
        "MTN",
        "out",
        re.compile(
            r"(?P<merchant>[A-Z][A-Z0-9 &'().,/-]+?)\s+has deducted UGX\s+(?P<amount>[\d,]+(?:\.\d+)?)"
            r".*?New balance is:UGX\s+(?P<balance>[\d,]+(?:\.\d+)?)",
            re.IGNORECASE | re.DOTALL,
        ),
    ),

    # ── MTN — outgoing cash withdrawal at agent ──────────────────────────────
    # "You have withdrawn UGX 25,000 on 2026-03-25 11:51:59.
    #  Fee: UGX 880, Tax: UGX 125. New balance: UGX 28,945.62."
    (
        "MTN",
        "out",
        re.compile(
            r"you have withdrawn UGX\s+(?P<amount>[\d,]+(?:\.\d+)?)\s+on\s+\d{4}-\d{2}-\d{2}"
            r".*?New balance:\s*UGX\s+(?P<balance>[\d,]+(?:\.\d+)?)",
            re.IGNORECASE | re.DOTALL,
        ),
    ),

    # ── MTN — incoming deposit from business ────────────────────────────────
    # "You have deposited UGX 650000 from ELIA INVESTMENTS LIMITED  on 2026-02-20 11:34:15.
    #  New balance: UGX 786818."
    (
        "MTN",
        "in",
        re.compile(
            r"you have deposited UGX\s+(?P<amount>[\d,]+(?:\.\d+)?)"
            r"\s+from\s+(?P<merchant>.+?)\s+on\s+\d{4}-\d{2}-\d{2}"
            r".*?New balance:\s*UGX\s+(?P<balance>[\d,]+(?:\.\d+)?)",
            re.IGNORECASE | re.DOTALL,
        ),
    ),

    # ── MTN — incoming cross-network from person ─────────────────────────────
    # "You have received UGX 40000 from Airtel Money on 2026-03-27 23:06:11. fee:0.
    #  Reason: ESTELLA WANDERA , 0750066399. New balance: UGX 47946."
    (
        "MTN",
        "in",
        re.compile(
            r"you have received UGX\s+(?P<amount>[\d,]+(?:\.\d+)?)"
            r"\s+from\s+(?:Airtel Money|MTN Mobile Money)\s+on\s+\d{4}-\d{2}-\d{2}"
            r".*?Reason:\s*(?P<merchant>[A-Z][A-Z ,]+?)\s*,\s*\d+"
            r".*?New balance:\s*UGX\s+(?P<balance>[\d,]+(?:\.\d+)?)",
            re.IGNORECASE | re.DOTALL,
        ),
    ),

    # ── MTN — legacy outgoing (older format) ────────────────────────────────
    # "You have sent UGX 10,000 to PEGASUS. Your new balance is UGX 45,000."
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

    # ── MTN — legacy incoming (older format) ────────────────────────────────
    # "You have received UGX 47,000 from PEGASUS PAYOUTS. Your new balance is UGX 92,000."
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

    # ── Airtel — incoming cash deposit ──────────────────────────────────────
    # "CASH DEPOSIT of UGX 2,000 from  MTN MOBILE MONEY UGANDA LTD.
    #  Bal UGX 278,767. TID 143779280993."
    (
        "Airtel",
        "in",
        re.compile(
            r"CASH DEPOSIT of UGX\s+(?P<amount>[\d,]+(?:\.\d+)?)"
            r"\s+from\s+(?P<merchant>.+?)\."
            r"\s*Bal UGX\s+(?P<balance>[\d,]+(?:\.\d+)?)",
            re.IGNORECASE | re.DOTALL,
        ),
    ),

    # ── Airtel — outgoing send (person or business) ──────────────────────────
    # "SENT UGX 40,000 to ARIEL EMMANUEL WANDERA on 256778556703.
    #  Fee UGX 500.0 Bal UGX 276,767."
    (
        "Airtel",
        "out",
        re.compile(
            r"SENT UGX\s+(?P<amount>[\d,]+(?:\.\d+)?)"
            r"\s+to\s+(?P<merchant>[^.]+?)\s+on\s+\d+"
            r".*?Bal UGX\s+(?P<balance>[\d,]+(?:\.\d+)?)",
            re.IGNORECASE | re.DOTALL,
        ),
    ),

    # ── Airtel — outgoing cash withdrawal at agent ───────────────────────────
    # "WITHDRAWN. TID 142289013602. UGX25,000 with Agent ID: 234328.
    #  Fee UGX 880.Tax UGX 125.Bal UGX 458,402."
    (
        "Airtel",
        "out",
        re.compile(
            r"WITHDRAWN\.\s*TID\s+\d+\.\s*UGX\s*(?P<amount>[\d,]+(?:\.\d+)?)\s+with Agent ID"
            r".*?Bal UGX\s+(?P<balance>[\d,]+(?:\.\d+)?)",
            re.IGNORECASE | re.DOTALL,
        ),
    ),

    # ── Airtel — legacy incoming deposit ────────────────────────────────────
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

    # ── Airtel — legacy outgoing payment ────────────────────────────────────
    # "UGX 10,000 sent to SAINTS BETTING successfully. Airtel Money Balance: UGX 35,000"
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
    "you have withdrawn",
    "cash deposit",
    "has deducted",
    "you have deposited",
    "sent ugx",
    "withdrawn",
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
