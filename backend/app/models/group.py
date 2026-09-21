import uuid
from sqlalchemy import Boolean, String, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base


class BucketPermission(Base):
    __tablename__ = "bucket_permissions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("groups.id", ondelete="CASCADE"), nullable=False, index=True
    )
    bucket_pattern: Mapped[str] = mapped_column(String(255), nullable=False)
    can_list: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    can_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    can_write: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    can_delete: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    group: Mapped["Group"] = relationship("Group", back_populates="permissions")


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Deliberately not eager-loaded: authenticating a user selectin-loads their
    # groups, and an eager Group.users would then pull in every member of each
    # group on every request. Group serialization (GroupRead) never includes
    # members, and user-assignment appends to User.groups without needing this
    # side loaded, so the default lazy strategy is both correct and cheaper.
    users: Mapped[list["User"]] = relationship(  # noqa: F821
        "User", secondary="user_groups", back_populates="groups"
    )
    permissions: Mapped[list[BucketPermission]] = relationship(
        "BucketPermission", back_populates="group", cascade="all, delete-orphan", lazy="selectin"
    )
