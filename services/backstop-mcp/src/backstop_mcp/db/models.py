from datetime import datetime

from sqlalchemy import (
    DateTime,
    LargeBinary,
    String,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class BackstopCredential(Base):
    """A user's Backstop username + personal API token, encrypted at rest."""

    __tablename__: str = "backstop_credentials"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    backstop_username: Mapped[str] = mapped_column(String, unique=True, index=True)
    encrypted_blob: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


__all__ = ["BackstopCredential", "Base"]
