"""The ORM tables this service owns.

Empty of tables so far, deliberately: every table this service will hold — registered OAuth
clients, pending authorizations, issued token families, and the encrypted With Intelligence
session per user — belongs to the auth feature, and lands in the same change as the code that
reads it. `Base` exists now because `db/migrations/env.py` needs metadata to autogenerate
against, and `alembic upgrade head` on an empty `versions/` is a no-op rather than an error.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
