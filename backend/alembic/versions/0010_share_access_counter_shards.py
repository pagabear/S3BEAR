"""Add sharded counters for high-concurrency share access

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-31

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "share_link_access_counters",
        sa.Column(
            "share_link_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("share_links.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("shard", sa.SmallInteger(), primary_key=True),
        sa.Column("access_count", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "shard >= 0 AND shard < 256",
            name="ck_share_access_counter_shard_range",
        ),
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE share_links AS links
            SET access_count = links.access_count + counters.access_count,
                last_accessed_at = CASE
                    WHEN links.last_accessed_at IS NULL
                        THEN counters.last_accessed_at
                    WHEN counters.last_accessed_at > links.last_accessed_at
                        THEN counters.last_accessed_at
                    ELSE links.last_accessed_at
                END
            FROM (
                SELECT share_link_id,
                       SUM(access_count) AS access_count,
                       MAX(last_accessed_at) AS last_accessed_at
                FROM share_link_access_counters
                GROUP BY share_link_id
            ) AS counters
            WHERE links.id = counters.share_link_id
            """
        )
    )
    op.drop_table("share_link_access_counters")