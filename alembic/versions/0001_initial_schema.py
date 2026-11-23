"""initial schema: endpoints, check_results, alerts

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-23
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "endpoints",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("method", sa.String(10), nullable=False),
        sa.Column("headers", sa.JSON(), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("expected_status", sa.Integer(), nullable=False),
        sa.Column("expected_body_contains", sa.String(500), nullable=True),
        sa.Column("max_latency_ms", sa.Integer(), nullable=True),
        sa.Column("interval_seconds", sa.Integer(), nullable=False),
        sa.Column("timeout_seconds", sa.Float(), nullable=False),
        sa.Column("max_retries", sa.Integer(), nullable=False),
        sa.Column("retry_backoff_seconds", sa.Float(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("current_status", sa.String(16), nullable=False),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_check_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_endpoints"),
        sa.UniqueConstraint("name", name="uq_endpoints_name"),
    )
    op.create_index("ix_endpoints_due", "endpoints", ["is_active", "next_check_at"])

    op.create_table(
        "check_results",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column("endpoint_id", sa.Integer(), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("response_time_ms", sa.Float(), nullable=True),
        sa.Column("is_success", sa.Boolean(), nullable=False),
        sa.Column("error_type", sa.String(32), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("is_anomaly", sa.Boolean(), nullable=False),
        sa.Column("anomaly_score", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(
            ["endpoint_id"],
            ["endpoints.id"],
            name="fk_check_results_endpoint_id_endpoints",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_check_results"),
    )
    op.create_index(
        "ix_check_results_endpoint_checked_at", "check_results", ["endpoint_id", "checked_at"]
    )
    op.create_index("ix_check_results_checked_at", "check_results", ["checked_at"])

    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("endpoint_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notified", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["endpoint_id"],
            ["endpoints.id"],
            name="fk_alerts_endpoint_id_endpoints",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_alerts"),
    )
    op.create_index(
        "ix_alerts_endpoint_kind_created", "alerts", ["endpoint_id", "kind", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_alerts_endpoint_kind_created", table_name="alerts")
    op.drop_table("alerts")
    op.drop_index("ix_check_results_checked_at", table_name="check_results")
    op.drop_index("ix_check_results_endpoint_checked_at", table_name="check_results")
    op.drop_table("check_results")
    op.drop_index("ix_endpoints_due", table_name="endpoints")
    op.drop_table("endpoints")
