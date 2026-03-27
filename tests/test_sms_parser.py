"""
Unit tests for sms_parser.py

Covers:
  - MTN outgoing payment (deposit to betting site)
  - MTN incoming deposit (withdrawal from betting site)
  - MTN cash withdrawal at agent
  - Airtel outgoing payment
  - Airtel incoming deposit
  - Amount parsing: commas, decimals, large numbers
  - Non-mobile-money SMS (personal messages, promos)
  - sim_hint propagation
  - Unknown mobile money format (keywords present, pattern unknown)
  - Edge cases: extra whitespace, mixed case, merchant names with spaces/numbers
"""
from decimal import Decimal

import pytest

from app.services.sms_parser import ParsedSMS, parse_sms


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def assert_parsed(
    sms: str,
    *,
    is_mm: bool,
    direction: str | None = None,
    amount: Decimal | None = None,
    merchant: str | None = None,
    balance: Decimal | None = None,
    sim: str | None = None,
    sim_hint: str | None = None,
) -> ParsedSMS:
    result = parse_sms(sms, sim_hint=sim_hint)
    assert result.raw == sms
    assert result.is_mobile_money == is_mm
    assert result.direction == direction
    assert result.amount == amount
    assert result.merchant_name == merchant
    assert result.balance == balance
    if sim is not None:
        assert result.sim == sim
    return result


# ---------------------------------------------------------------------------
# MTN outgoing payments
# ---------------------------------------------------------------------------

def test_mtn_outgoing_basic():
    """Standard MTN send-money SMS."""
    sms = (
        "You have sent UGX 10,000 to PEGASUS. "
        "Your new balance is UGX 45,000. Transaction ID: TXN001"
    )
    assert_parsed(
        sms,
        is_mm=True,
        direction="out",
        amount=Decimal("10000"),
        merchant="PEGASUS",
        balance=Decimal("45000"),
        sim="MTN",
    )


def test_mtn_outgoing_large_amount():
    """MTN outgoing with a 7-digit amount (1.5 million UGX)."""
    sms = (
        "You have sent UGX 1,500,000 to SPORTS ARENA. "
        "Your new balance is UGX 200,000. Transaction ID: TXN999"
    )
    assert_parsed(
        sms,
        is_mm=True,
        direction="out",
        amount=Decimal("1500000"),
        merchant="SPORTS ARENA",
        balance=Decimal("200000"),
        sim="MTN",
    )


def test_mtn_outgoing_merchant_with_spaces():
    """Merchant name with multiple words."""
    sms = (
        "You have sent UGX 25,000 to SAINTS BETTING LTD. "
        "Your new balance is UGX 75,000. Transaction ID: TXN202"
    )
    assert_parsed(
        sms,
        is_mm=True,
        direction="out",
        amount=Decimal("25000"),
        merchant="SAINTS BETTING LTD",
        balance=Decimal("75000"),
        sim="MTN",
    )


def test_mtn_outgoing_no_txn_id():
    """MTN outgoing SMS without a trailing Transaction ID (some operator variants)."""
    sms = (
        "You have sent UGX 5,000 to ODIBETS. "
        "Your new balance is UGX 15,000."
    )
    assert_parsed(
        sms,
        is_mm=True,
        direction="out",
        amount=Decimal("5000"),
        merchant="ODIBETS",
        balance=Decimal("15000"),
        sim="MTN",
    )


def test_mtn_outgoing_amount_with_decimal():
    """Amount expressed with decimal places."""
    sms = (
        "You have sent UGX 10,000.50 to BETWAY UG. "
        "Your new balance is UGX 4,999.50. Transaction ID: TXN303"
    )
    assert_parsed(
        sms,
        is_mm=True,
        direction="out",
        amount=Decimal("10000.50"),
        merchant="BETWAY UG",
        balance=Decimal("4999.50"),
        sim="MTN",
    )


def test_mtn_outgoing_case_insensitive():
    """Parser handles lower-case SMS body (some aggregators reformat)."""
    sms = (
        "you have sent ugx 8,000 to sportpesa. "
        "your new balance is ugx 12,000. transaction id: txn404"
    )
    assert_parsed(
        sms,
        is_mm=True,
        direction="out",
        amount=Decimal("8000"),
        merchant="sportpesa",
        balance=Decimal("12000"),
        sim="MTN",
    )


# ---------------------------------------------------------------------------
# MTN incoming deposits
# ---------------------------------------------------------------------------

def test_mtn_incoming_from_betting_site():
    """MTN incoming — a withdrawal payout from a betting aggregator."""
    sms = (
        "You have received UGX 47,000 from PEGASUS PAYOUTS. "
        "Your new balance is UGX 92,000."
    )
    assert_parsed(
        sms,
        is_mm=True,
        direction="in",
        amount=Decimal("47000"),
        merchant="PEGASUS PAYOUTS",
        balance=Decimal("92000"),
        sim="MTN",
    )


def test_mtn_incoming_from_person():
    """MTN incoming — transfer from a person (not a betting site)."""
    sms = (
        "You have received UGX 20,000 from JOHN DOE. "
        "Your new balance is UGX 35,000."
    )
    assert_parsed(
        sms,
        is_mm=True,
        direction="in",
        amount=Decimal("20000"),
        merchant="JOHN DOE",
        balance=Decimal("35000"),
        sim="MTN",
    )


# ---------------------------------------------------------------------------
# MTN cash withdrawal
# ---------------------------------------------------------------------------

def test_mtn_cash_withdrawal():
    """MTN withdrawal at an agent — direction=out, no merchant."""
    sms = (
        "Your withdrawal of UGX 30,000 was successful. "
        "Your new balance is UGX 10,000."
    )
    result = parse_sms(sms)
    assert result.is_mobile_money is True
    assert result.direction == "out"
    assert result.amount == Decimal("30000")
    assert result.merchant_name is None  # no merchant in withdrawal SMS
    assert result.balance == Decimal("10000")
    assert result.sim == "MTN"


# ---------------------------------------------------------------------------
# Airtel outgoing payments
# ---------------------------------------------------------------------------

def test_airtel_outgoing_basic():
    """Standard Airtel send-money SMS."""
    sms = (
        "UGX 15,000 sent to SAINTS BETTING successfully. "
        "Airtel Money Balance: UGX 85,000"
    )
    assert_parsed(
        sms,
        is_mm=True,
        direction="out",
        amount=Decimal("15000"),
        merchant="SAINTS BETTING",
        balance=Decimal("85000"),
        sim="Airtel",
    )


def test_airtel_outgoing_merchant_with_numbers():
    """Airtel outgoing — merchant name includes digits."""
    sms = (
        "UGX 50,000 sent to BETWAY256 successfully. "
        "Airtel Money Balance: UGX 150,000"
    )
    assert_parsed(
        sms,
        is_mm=True,
        direction="out",
        amount=Decimal("50000"),
        merchant="BETWAY256",
        balance=Decimal("150000"),
        sim="Airtel",
    )


def test_airtel_outgoing_large_balance():
    """Airtel outgoing — large balance figure."""
    sms = (
        "UGX 100,000 sent to ODIBETS AGGREGATOR successfully. "
        "Airtel Money Balance: UGX 2,400,000"
    )
    assert_parsed(
        sms,
        is_mm=True,
        direction="out",
        amount=Decimal("100000"),
        merchant="ODIBETS AGGREGATOR",
        balance=Decimal("2400000"),
        sim="Airtel",
    )


# ---------------------------------------------------------------------------
# Airtel incoming deposits
# ---------------------------------------------------------------------------

def test_airtel_incoming_from_betting_site():
    """Airtel incoming — payout from a betting aggregator."""
    sms = (
        "You have received UGX 200,000 on your Airtel Money account "
        "from SAINTS PAYOUTS."
    )
    assert_parsed(
        sms,
        is_mm=True,
        direction="in",
        amount=Decimal("200000"),
        merchant="SAINTS PAYOUTS",
        sim="Airtel",
    )


def test_airtel_incoming_from_person():
    """Airtel incoming — person-to-person transfer."""
    sms = (
        "You have received UGX 10,000 on your Airtel Money account "
        "from MARY NAMUKASA."
    )
    assert_parsed(
        sms,
        is_mm=True,
        direction="in",
        amount=Decimal("10000"),
        merchant="MARY NAMUKASA",
        sim="Airtel",
    )


# ---------------------------------------------------------------------------
# Non-mobile-money SMS
# ---------------------------------------------------------------------------

def test_non_mm_personal_message():
    """Plain text personal message — not mobile money."""
    assert_parsed(
        "Hey, are you coming to the meeting tomorrow?",
        is_mm=False,
        direction=None,
        amount=None,
        merchant=None,
        balance=None,
    )


def test_non_mm_promotional_sms():
    """Promotional SMS without mobile money keywords."""
    assert_parsed(
        "Congratulations! You've won a free data bundle. Reply YES to claim.",
        is_mm=False,
    )


def test_non_mm_bank_notification():
    """Bank SMS that doesn't use UGX keyword format."""
    assert_parsed(
        "Your Stanbic account 1234 has been credited with 50000 UGX.",
        # "UGX" appears but none of our specific patterns match
        # → is_mm=True (keyword hit), direction=None
        is_mm=True,
        direction=None,
    )


# ---------------------------------------------------------------------------
# sim_hint propagation
# ---------------------------------------------------------------------------

def test_sim_hint_overrides_detected_sim():
    """sim_hint is preferred over regex-detected sim label."""
    sms = (
        "You have sent UGX 10,000 to PEGASUS. "
        "Your new balance is UGX 45,000."
    )
    result = parse_sms(sms, sim_hint="MTN")
    assert result.sim == "MTN"


def test_sim_hint_preserved_on_non_mm():
    """sim_hint stored even when SMS is not mobile money."""
    result = parse_sms("Hello there!", sim_hint="Airtel")
    assert result.is_mobile_money is False
    assert result.sim == "Airtel"


# ---------------------------------------------------------------------------
# Unknown mobile money format
# ---------------------------------------------------------------------------

def test_unknown_mm_format_returns_is_mm_true():
    """
    SMS contains mobile money keywords but doesn't match any pattern.
    Should return is_mobile_money=True with direction=None so the
    backend can flag it for manual review rather than silently ignoring it.
    """
    sms = "MTN Mobile Money: Transaction of UGX 5,000 processed. Ref: XYZ789"
    result = parse_sms(sms)
    assert result.is_mobile_money is True
    assert result.direction is None
    assert result.amount is None


# ---------------------------------------------------------------------------
# raw field preservation
# ---------------------------------------------------------------------------

def test_raw_is_always_original():
    """result.raw must be the exact input, untouched."""
    sms = "  You have sent UGX 1,000 to TEST.  Your new balance is UGX 2,000.  "
    result = parse_sms(sms)
    assert result.raw == sms
