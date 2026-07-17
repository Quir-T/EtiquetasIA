"""initial schema

Revision ID: 001_initial_schema
Revises:
Create Date: 2026-07-16 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


process_status_enum = sa.Enum(
    "success",
    "provider_error",
    "validation_error",
    "timeout",
    name="process_status_enum",
)


def upgrade() -> None:
    op.create_table(
        "anamnesis_processing_events",
        sa.Column("process_id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("patient_id", sa.Integer(), nullable=False),
        sa.Column("doctor_id", sa.Integer(), nullable=False),
        sa.Column("anonymized_text", sa.Text(), nullable=False),
        sa.Column("labels_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", process_status_enum, nullable=False, server_default=sa.text("'success'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_anamnesis_processing_events_patient_id", "anamnesis_processing_events", ["patient_id"], unique=False)
    op.create_index("ix_anamnesis_processing_events_doctor_id", "anamnesis_processing_events", ["doctor_id"], unique=False)
    op.create_index("ix_anamnesis_processing_events_created_at", "anamnesis_processing_events", ["created_at"], unique=False)

    op.create_table(
        "anamnesis_processing_audit",
        sa.Column("audit_id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("process_id", sa.String(length=36), nullable=False, unique=True),
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("error_code", sa.String(length=50), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("processing_ms", sa.Integer(), nullable=False),
        sa.Column("prompt_version", sa.String(length=50), nullable=False),
        sa.Column("labels_catalog_version", sa.String(length=50), nullable=False),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("provider_model", sa.String(length=80), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("processing_ms >= 0", name="ck_anamnesis_processing_audit_processing_ms_non_negative"),
    )
    op.create_foreign_key(
        "fk_anamnesis_audit_process_id",
        "anamnesis_processing_audit",
        "anamnesis_processing_events",
        ["process_id"],
        ["process_id"],
    )
    op.create_index("ix_anamnesis_processing_audit_created_at", "anamnesis_processing_audit", ["created_at"], unique=False)
    op.create_index("ix_anamnesis_processing_audit_status", "anamnesis_processing_audit", ["status"], unique=False)

    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_row_modification()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'Rows are immutable';
        END;
        $$;
        """
    )

    op.execute(
        """
        CREATE TRIGGER trg_prevent_update_delete_anamnesis_events
        BEFORE UPDATE OR DELETE ON anamnesis_processing_events
        FOR EACH ROW EXECUTE FUNCTION prevent_row_modification();
        """
    )

    op.execute(
        """
        CREATE TRIGGER trg_prevent_update_delete_anamnesis_audit
        BEFORE UPDATE OR DELETE ON anamnesis_processing_audit
        FOR EACH ROW EXECUTE FUNCTION prevent_row_modification();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_prevent_update_delete_anamnesis_audit ON anamnesis_processing_audit;")
    op.execute("DROP TRIGGER IF EXISTS trg_prevent_update_delete_anamnesis_events ON anamnesis_processing_events;")
    op.execute("DROP FUNCTION IF EXISTS prevent_row_modification();")

    op.drop_index("ix_anamnesis_processing_audit_status", table_name="anamnesis_processing_audit")
    op.drop_index("ix_anamnesis_processing_audit_created_at", table_name="anamnesis_processing_audit")
    op.drop_constraint("fk_anamnesis_audit_process_id", "anamnesis_processing_audit", type_="foreignkey")
    op.drop_table("anamnesis_processing_audit")

    op.drop_index("ix_anamnesis_processing_events_created_at", table_name="anamnesis_processing_events")
    op.drop_index("ix_anamnesis_processing_events_doctor_id", table_name="anamnesis_processing_events")
    op.drop_index("ix_anamnesis_processing_events_patient_id", table_name="anamnesis_processing_events")
    op.drop_table("anamnesis_processing_events")
    process_status_enum.drop(op.get_bind(), checkfirst=False)
