"""SQLAlchemy models that store immutable anamnesis processing events and their audit records."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from src.domain.entities.anamnesis_event import ProcessStatus


class Base(DeclarativeBase):
    pass


process_status_db_enum = Enum(
    ProcessStatus,
    name="process_status_enum",
    values_callable=lambda enum: [member.value for member in enum],
    validate_strings=True,
)


class AnamnesisEventModel(Base):
    __tablename__ = "anamnesis_processing_events"

    process_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    patient_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    doctor_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    anonymized_text: Mapped[str] = mapped_column(Text, nullable=False)
    labels_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[ProcessStatus] = mapped_column(
        process_status_db_enum,
        nullable=False,
        default=ProcessStatus.SUCCESS,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)


class AnamnesisAuditModel(Base):
    __tablename__ = "anamnesis_processing_audit"

    audit_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    process_id: Mapped[str] = mapped_column(
        ForeignKey("anamnesis_processing_events.process_id", name="fk_anamnesis_audit_process_id"),
        nullable=False,
        unique=True,
    )
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[ProcessStatus] = mapped_column(process_status_db_enum, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    processing_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(50), nullable=False)
    labels_catalog_version: Mapped[str] = mapped_column(String(50), nullable=False)
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    provider_model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
