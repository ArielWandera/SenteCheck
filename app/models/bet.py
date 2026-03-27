from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base

RESULT_WIN = "win"
RESULT_LOSS = "loss"
RESULT_PENDING = "pending"


class Bet(Base):
    __tablename__ = "bets"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    # nullable — manually logged bets may not have a linked transaction
    transaction_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"))
    stake: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    result: Mapped[str] = mapped_column(String(10), nullable=False, default=RESULT_PENDING)
    return_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    platform: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="bets")  # noqa: F821
    transaction: Mapped["Transaction | None"] = relationship(  # noqa: F821
        back_populates="bet"
    )

    @property
    def net(self) -> Decimal:
        if self.result == RESULT_WIN and self.return_amount is not None:
            return self.return_amount - self.stake
        if self.result == RESULT_LOSS:
            return -self.stake
        return Decimal("0")

    def __repr__(self) -> str:
        return f"<Bet id={self.id} stake={self.stake} result={self.result}>"
