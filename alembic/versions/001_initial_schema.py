"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-03-27

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable pgcrypto for future raw_sms encryption (Step 11)
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=100), nullable=True),
        sa.Column("bankroll", sa.Numeric(precision=12, scale=2), nullable=False, server_default="0"),
        sa.Column(
            "onboarded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("consent_given", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("consent_given_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consent_version", sa.String(length=10), nullable=False, server_default="v1"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("telegram_id"),
    )

    op.create_table(
        "transactions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("merchant_name", sa.String(length=200), nullable=True),
        sa.Column(
            "category",
            sa.String(length=50),
            nullable=False,
            server_default="unclassified",
        ),
        sa.Column("direction", sa.String(length=10), nullable=False),
        sa.Column("raw_sms", sa.Text(), nullable=True),
        sa.Column(
            "source",
            sa.String(length=20),
            nullable=False,
            server_default="android_app",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "bets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("transaction_id", sa.Integer(), nullable=True),
        sa.Column("stake", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("result", sa.String(length=10), nullable=False, server_default="pending"),
        sa.Column("return_amount", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("platform", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "known_merchants",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("merchant_name", sa.String(length=200), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("direction", sa.String(length=10), nullable=False),
        sa.Column("platform", sa.String(length=100), nullable=True),
        sa.Column("is_global", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("confirmed_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        # Unique on (merchant_name, direction, user_id).
        # NULLS NOT DISTINCT ensures global entries (user_id=NULL) are also deduplicated.
        # Requires PostgreSQL 15+.
        sa.UniqueConstraint(
            "merchant_name",
            "direction",
            "user_id",
            postgresql_nulls_not_distinct=True,
        ),
    )


def downgrade() -> None:
    op.drop_table("known_merchants")
    op.drop_table("bets")
    op.drop_table("transactions")
    op.drop_table("users")
