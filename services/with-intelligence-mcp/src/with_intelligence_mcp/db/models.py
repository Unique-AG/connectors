"""Service-owned ORM models."""

import uuid
from datetime import datetime

from mcp_credential_auth import AuthBase as Base
from sqlalchemy import DateTime, LargeBinary, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column


class WithIntelligenceSession(Base):
    __tablename__: str = "with_intelligence_sessions"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    wi_username: Mapped[str] = mapped_column(String, unique=True, index=True)
    encrypted_blob: Mapped[bytes] = mapped_column(LargeBinary)
    refresh_claim_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    refresh_claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


__all__ = ["Base", "WithIntelligenceSession"]
