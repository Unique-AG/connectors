from datetime import datetime

from sqlalchemy import Computed
from sqlalchemy import DateTime
from sqlalchemy import Integer
from sqlalchemy import LargeBinary
from sqlalchemy import Text
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column


class Base(DeclarativeBase):
    """Every table's model subclasses it, so `alembic revision --autogenerate` sees it."""


class ResponseCacheRow(Base):
    """One Polixis answer, under the request it answers, with what the cull needs: when it
    expires, its size, and when it was last read.
    """

    __tablename__: str = "polixis_response_cache"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    body: Mapped[bytes] = mapped_column(LargeBinary)
    size_bytes: Mapped[int] = mapped_column(Integer, Computed("octet_length(body)", persisted=True))
    cached_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reads: Mapped[int] = mapped_column(Integer, server_default="0")
