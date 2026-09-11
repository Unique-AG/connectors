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
    """A user's Backstop username + personal API token, encrypted at rest.

    `external_user_id` / `raw` are the Backstop `system-users` record captured at login —
    `get_current_caller_system_user` reads them via the token `subject` (`user_id`).
    """

    __tablename__: str = "backstop_credentials"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    backstop_username: Mapped[str] = mapped_column(String, unique=True, index=True)
    encrypted_blob: Mapped[bytes] = mapped_column(LargeBinary)
    external_user_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    raw: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


__all__ = ["BackstopCredential", "Base"]
