from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base

# Threshold of unique user confirmations before a merchant is promoted to global
GLOBAL_CONFIRMATION_THRESHOLD = 3


class KnownMerchant(Base):
    __tablename__ = "known_merchants"

    # Unique constraint: one entry per (merchant_name, direction, user_id) combination.
    # For global merchants (user_id IS NULL) postgresql_nulls_not_distinct=True ensures
    # (PEGASUS, out, NULL) cannot be inserted twice — requires PostgreSQL 15+.
    __table_args__ = (
        UniqueConstraint(
            "merchant_name",
            "direction",
            "user_id",
            postgresql_nulls_not_distinct=True,
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    merchant_name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    platform: Mapped[str | None] = mapped_column(String(100))
    is_global: Mapped[bool] = mapped_column(Boolean, default=False)
    # NULL when is_global = TRUE
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    confirmed_count: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped["User | None"] = relationship(back_populates="known_merchants")  # noqa: F821

    def __repr__(self) -> str:
        scope = "global" if self.is_global else f"user={self.user_id}"
        return (
            f"<KnownMerchant {self.merchant_name!r} "
            f"direction={self.direction} category={self.category} {scope}>"
        )
