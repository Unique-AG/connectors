"""The ORM tables this service owns.

No tables yet: they belong to the auth feature and land with the code that reads them.
`Base` exists so `db/migrations/env.py` has metadata to autogenerate against.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
