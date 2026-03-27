"""encrypt raw_sms column

Revision ID: 002
Revises: 001
Create Date: 2026-03-27

Changes raw_sms from TEXT to BYTEA so the application-level Fernet cipher
can store opaque ciphertext.  The pgcrypto extension (enabled in migration
001) remains available for any future SQL-level encryption needs.

Data migration note
-------------------
If upgrading a database that already has plaintext raw_sms rows, those rows
will remain readable via the TypeDecorator fallback path (which returns raw
bytes decoded as UTF-8 when decryption fails).  To properly re-encrypt them,
run the one-off script tools/reencrypt_sms.py after deploying.
For a fresh Railway deployment there are no existing rows — no action needed.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("transactions") as batch_op:
        batch_op.alter_column(
            "raw_sms",
            existing_type=sa.Text(),
            type_=sa.LargeBinary(),
            # PostgreSQL: cast existing TEXT to BYTEA via encode()
            postgresql_using="encode(raw_sms::bytea, 'escape')::bytea",
            existing_nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("transactions") as batch_op:
        batch_op.alter_column(
            "raw_sms",
            existing_type=sa.LargeBinary(),
            type_=sa.Text(),
            postgresql_using="convert_from(raw_sms, 'UTF8')",
            existing_nullable=True,
        )
