from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base
from app.utils.encryption import make_encrypted_text_type

# Valid values for category and direction
CATEGORY_BET_DEPOSIT = "bet_deposit"
CATEGORY_BET_WITHDRAWAL = "bet_withdrawal"
CATEGORY_OTHER_PAYMENT = "other_payment"
CATEGORY_OTHER_INCOME = "other_income"
CATEGORY_UNCLASSIFIED = "unclassified"

DIRECTION_OUT = "out"
DIRECTION_IN = "in"

SOURCE_ANDROID = "android_app"
SOURCE_MANUAL = "manual"


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    merchant_name: Mapped[str | None] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(
        String(50), nullable=False, default=CATEGORY_UNCLASSIFIED
    )
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    # Stored as BYTEA (LargeBinary) and encrypted via Fernet before reaching the DB.
    # Decrypted transparently on read. Key = ENCRYPTION_KEY env var.
    raw_sms: Mapped[str | None] = mapped_column(make_encrypted_text_type())
    source: Mapped[str] = mapped_column(String(20), nullable=False, default=SOURCE_ANDROID)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="transactions")  # noqa: F821
    bet: Mapped["Bet | None"] = relationship(  # noqa: F821
        back_populates="transaction", uselist=False
    )

    def __repr__(self) -> str:
        return (
            f"<Transaction id={self.id} direction={self.direction} "
            f"amount={self.amount} category={self.category}>"
        )
