"""per-endpoint alert email recipients

Revision ID: 0003_alert_emails
Revises: 0002_maintenance_ssl_status
Create Date: 2026-11-23
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_alert_emails"
down_revision: str | None = "0002_maintenance_ssl_status"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("endpoints") as batch:
        batch.add_column(
            sa.Column("alert_emails", sa.JSON(), nullable=False, server_default=sa.text("'[]'"))
        )


def downgrade() -> None:
    with op.batch_alter_table("endpoints") as batch:
        batch.drop_column("alert_emails")
