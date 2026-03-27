from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# Import all models so Alembic can discover them for autogenerate
from app.models.user import User  # noqa: F401, E402
from app.models.transaction import Transaction  # noqa: F401, E402
from app.models.bet import Bet  # noqa: F401, E402
from app.models.known_merchant import KnownMerchant  # noqa: F401, E402
