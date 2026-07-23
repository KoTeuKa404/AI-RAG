"""Add document ACLs and chat feedback.

Revision ID: 0002_access_feedback
Revises: 0001_initial
Create Date: 2026-07-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_access_feedback"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column(
            "visibility",
            sa.String(length=32),
            nullable=False,
            server_default="workspace",
        ),
    )
    op.add_column(
        "documents",
        sa.Column(
            "allowed_groups",
            postgresql.ARRAY(sa.String(length=120)),
            nullable=False,
            server_default=sa.text("ARRAY[]::varchar[]"),
        ),
    )
    op.add_column(
        "documents",
        sa.Column("created_by", sa.String(length=120), nullable=True),
    )
    op.create_check_constraint(
        "ck_documents_visibility",
        "documents",
        "visibility IN ('workspace', 'restricted')",
    )

    op.add_column(
        "chat_logs",
        sa.Column("actor_id", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "chat_logs",
        sa.Column("feedback_rating", sa.SmallInteger(), nullable=True),
    )
    op.add_column(
        "chat_logs",
        sa.Column("feedback_comment", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_chat_logs_workspace_actor",
        "chat_logs",
        ["workspace_id", "actor_id"],
    )
    op.create_check_constraint(
        "ck_chat_logs_feedback_rating",
        "chat_logs",
        "feedback_rating IS NULL OR feedback_rating BETWEEN 1 AND 5",
    )


def downgrade() -> None:
    op.drop_constraint("ck_chat_logs_feedback_rating", "chat_logs", type_="check")
    op.drop_index("ix_chat_logs_workspace_actor", table_name="chat_logs")
    op.drop_column("chat_logs", "feedback_comment")
    op.drop_column("chat_logs", "feedback_rating")
    op.drop_column("chat_logs", "actor_id")

    op.drop_constraint("ck_documents_visibility", "documents", type_="check")
    op.drop_column("documents", "created_by")
    op.drop_column("documents", "allowed_groups")
    op.drop_column("documents", "visibility")
