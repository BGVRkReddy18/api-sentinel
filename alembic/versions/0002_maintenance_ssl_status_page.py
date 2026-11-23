"""maintenance windows, TLS certificate tracking, public status page

Revision ID: 0002_maintenance_ssl_status
Revises: 0001_initial
Create Date: 2026-11-23
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_maintenance_ssl_status"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("endpoints") as batch:
        batch.add_column(sa.Column("is_public", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("maintenance_until", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("maintenance_reason", sa.String(200), nullable=True))
        batch.add_column(sa.Column("ssl_expires_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("ssl_checked_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("ssl_error", sa.String(300), nullable=True))

    with op.batch_alter_table("check_results") as batch:
        batch.add_column(
            sa.Column("in_maintenance", sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade() -> None:
    with op.batch_alter_table("check_results") as batch:
        batch.drop_column("in_maintenance")
    with op.batch_alter_table("endpoints") as batch:
        for column in (
            "ssl_error",
            "ssl_checked_at",
            "ssl_expires_at",
            "maintenance_reason",
            "maintenance_until",
            "is_public",
        ):
            batch.drop_column(column)
