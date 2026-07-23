"""Declarative base and shared model mixins."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, MetaData, text
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column
from sqlalchemy.sql import func

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base class for every ORM model."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UUIDPrimaryKeyMixin:
    """Server-generated UUID primary key."""

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )


class TimestampMixin:
    """Server-managed creation and update timestamps."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class WorkspaceOwnedModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Base for tenant-owned rows; every query must filter on `workspace_id`."""

    __abstract__ = True

    @declared_attr
    def workspace_id(cls) -> Mapped[uuid.UUID]:  # noqa: N805 - SQLAlchemy declared_attr
        return mapped_column(
            ForeignKey("workspaces.id", ondelete="CASCADE"),
            index=True,
        )
