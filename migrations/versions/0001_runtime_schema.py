"""create runtime schema

Revision ID: 0001_runtime_schema
Revises:
Create Date: 2026-03-18 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_runtime_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agents",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("version", sa.String(length=50), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_agents_status", "agents", ["status"], unique=False)
    op.create_index("idx_agents_created_at", "agents", ["created_at"], unique=False)

    op.create_table(
        "tasks",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("thread_id", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("dag", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("current_step", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_tasks_agent_id", "tasks", ["agent_id"], unique=False)
    op.create_index("idx_tasks_status", "tasks", ["status"], unique=False)

    op.create_table(
        "task_steps",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("action_type", sa.String(length=20), nullable=False),
        sa.Column("plan", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("model_used", sa.String(length=100), nullable=False),
        sa.Column(
            "token_usage",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "trace_meta",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_task_steps_task_step",
        "task_steps",
        ["task_id", "step_index"],
        unique=False,
    )

    op.create_table(
        "tool_logs",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("task_step_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("tool_name", sa.String(length=255), nullable=False),
        sa.Column("input_params", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("output_result", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("sandbox_type", sa.String(length=20), nullable=False, server_default="mock"),
        sa.Column(
            "permissions_used",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["task_step_id"], ["task_steps.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_tool_logs_task_step_id", "tool_logs", ["task_step_id"], unique=False)
    op.create_index("idx_tool_logs_tool_name", "tool_logs", ["tool_name"], unique=False)
    op.create_index("idx_tool_logs_success", "tool_logs", ["success"], unique=False)

    op.create_table(
        "checkpoint_migrations",
        sa.Column("v", sa.Integer(), nullable=False, autoincrement=False),
        sa.PrimaryKeyConstraint("v"),
    )
    op.bulk_insert(
        sa.table("checkpoint_migrations", sa.column("v", sa.Integer())),
        [{"v": version} for version in range(10)],
    )

    op.create_table(
        "checkpoints",
        sa.Column("thread_id", sa.Text(), nullable=False),
        sa.Column("checkpoint_ns", sa.Text(), nullable=False, server_default=""),
        sa.Column("checkpoint_id", sa.Text(), nullable=False),
        sa.Column("parent_checkpoint_id", sa.Text(), nullable=True),
        sa.Column("type", sa.Text(), nullable=True),
        sa.Column("checkpoint", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.PrimaryKeyConstraint("thread_id", "checkpoint_ns", "checkpoint_id"),
    )
    op.create_index("checkpoints_thread_id_idx", "checkpoints", ["thread_id"], unique=False)

    op.create_table(
        "checkpoint_blobs",
        sa.Column("thread_id", sa.Text(), nullable=False),
        sa.Column("checkpoint_ns", sa.Text(), nullable=False, server_default=""),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("blob", postgresql.BYTEA(), nullable=True),
        sa.PrimaryKeyConstraint("thread_id", "checkpoint_ns", "channel", "version"),
    )
    op.create_index(
        "checkpoint_blobs_thread_id_idx",
        "checkpoint_blobs",
        ["thread_id"],
        unique=False,
    )

    op.create_table(
        "checkpoint_writes",
        sa.Column("thread_id", sa.Text(), nullable=False),
        sa.Column("checkpoint_ns", sa.Text(), nullable=False, server_default=""),
        sa.Column("checkpoint_id", sa.Text(), nullable=False),
        sa.Column("task_id", sa.Text(), nullable=False),
        sa.Column("idx", sa.Integer(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=True),
        sa.Column("blob", postgresql.BYTEA(), nullable=False),
        sa.Column("task_path", sa.Text(), nullable=False, server_default=""),
        sa.PrimaryKeyConstraint("thread_id", "checkpoint_ns", "checkpoint_id", "task_id", "idx"),
    )
    op.create_index(
        "checkpoint_writes_thread_id_idx",
        "checkpoint_writes",
        ["thread_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("checkpoint_writes_thread_id_idx", table_name="checkpoint_writes")
    op.drop_table("checkpoint_writes")
    op.drop_index("checkpoint_blobs_thread_id_idx", table_name="checkpoint_blobs")
    op.drop_table("checkpoint_blobs")
    op.drop_index("checkpoints_thread_id_idx", table_name="checkpoints")
    op.drop_table("checkpoints")
    op.drop_table("checkpoint_migrations")

    op.drop_index("idx_tool_logs_success", table_name="tool_logs")
    op.drop_index("idx_tool_logs_tool_name", table_name="tool_logs")
    op.drop_index("idx_tool_logs_task_step_id", table_name="tool_logs")
    op.drop_table("tool_logs")

    op.drop_index("idx_task_steps_task_step", table_name="task_steps")
    op.drop_table("task_steps")

    op.drop_index("idx_tasks_status", table_name="tasks")
    op.drop_index("idx_tasks_agent_id", table_name="tasks")
    op.drop_table("tasks")

    op.drop_index("idx_agents_created_at", table_name="agents")
    op.drop_index("idx_agents_status", table_name="agents")
    op.drop_table("agents")
