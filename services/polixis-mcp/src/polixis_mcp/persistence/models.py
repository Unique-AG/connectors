from datetime import datetime

from sqlalchemy import Computed
from sqlalchemy import DateTime
from sqlalchemy import Double
from sqlalchemy import Index
from sqlalchemy import Integer
from sqlalchemy import LargeBinary
from sqlalchemy import Text
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column


class Base(DeclarativeBase):
    """Every table's model subclasses it, so `alembic revision --autogenerate` sees it."""


class KeyValueRow(Base):
    """The table `PostgreSQLStore` keeps its entries in, as it would make it, which the store is
    told not to do: the migrations make every table.
    """

    __tablename__: str = "kv_store"
    __table_args__: tuple[Index, ...] = (
        Index(
            "idx_kv_store_expires_at",
            "expires_at",
            postgresql_where=text("expires_at IS NOT NULL"),
        ),
    )

    collection: Mapped[str] = mapped_column(Text, primary_key=True)
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[dict[str, object]] = mapped_column(JSONB)
    ttl: Mapped[float | None] = mapped_column(Double)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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
    # Unused; kept until no release that can still run during a rollout writes it.
    reads: Mapped[int] = mapped_column(Integer, server_default="0")
