from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Every table's model subclasses it, so `alembic revision --autogenerate` sees it."""
