"""PostgreSQL repository that persists events, audit rows and process lookups."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from src.domain.entities.anamnesis_event import AnamnesisEvent, ProcessStatus
from src.domain.exceptions.domain_exceptions import PersistenceError
from src.domain.interfaces.repository import AnamnesisRepositoryInterface
from src.infrastructure.persistence.models import AnamnesisAuditModel, AnamnesisEventModel


@dataclass(slots=True)
class PostgresAnamnesisRepository(AnamnesisRepositoryInterface):
    engine: Engine

    def __post_init__(self) -> None:
        self._session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)

    def _to_entity(self, model: AnamnesisEventModel) -> AnamnesisEvent:
        return AnamnesisEvent(
            process_id=model.process_id,
            patient_id=model.patient_id,
            doctor_id=model.doctor_id,
            anonymized_text=model.anonymized_text,
            prompt_version="n/a",
            labels_catalog_version="n/a",
            provider="n/a",
            provider_model=None,
            labels_json=model.labels_json,
            status=ProcessStatus(model.status),
            error_code=None,
            error_message=None,
            processing_ms=0,
            created_at=model.created_at,
        )

    def _to_model(self, event: AnamnesisEvent) -> AnamnesisEventModel:
        return AnamnesisEventModel(
            process_id=event.process_id,
            patient_id=event.patient_id,
            doctor_id=event.doctor_id,
            anonymized_text=event.anonymized_text,
            labels_json=event.labels_json,
            status=event.status.value,
            created_at=event.created_at,
        )

    def _to_audit_model(self, event: AnamnesisEvent) -> AnamnesisAuditModel:
        return AnamnesisAuditModel(
            audit_id=str(uuid4()),
            process_id=event.process_id,
            action="process_anamnesis",
            status=event.status.value,
            error_code=event.error_code,
            error_message=event.error_message,
            processing_ms=event.processing_ms,
            prompt_version=event.prompt_version,
            labels_catalog_version=event.labels_catalog_version,
            provider=event.provider,
            provider_model=event.provider_model,
            metadata_json={
                "text_length": len(event.anonymized_text),
            },
            created_at=event.created_at,
        )

    @staticmethod
    def _audit_to_dict(model: AnamnesisAuditModel) -> dict[str, Any]:
        return {
            "audit_id": model.audit_id,
            "process_id": model.process_id,
            "action": model.action,
            "status": model.status,
            "error_code": model.error_code,
            "error_message": model.error_message,
            "processing_ms": model.processing_ms,
            "prompt_version": model.prompt_version,
            "labels_catalog_version": model.labels_catalog_version,
            "provider": model.provider,
            "provider_model": model.provider_model,
            "metadata_json": model.metadata_json,
            "created_at": model.created_at,
        }

    def save(self, event: AnamnesisEvent) -> AnamnesisEvent:
        try:
            with self._session_factory() as session:
                model = self._to_model(event)
                session.add(model)
                # Hacer flush del insert padre primero para que el FK de auditoria siempre vea process_id.
                session.flush()

                audit_model = self._to_audit_model(event)
                session.add(audit_model)
                session.commit()
                return event
        except Exception as exc:
            raise PersistenceError(str(exc)) from exc

    def get_by_process_id(self, process_id: str) -> Optional[AnamnesisEvent]:
        try:
            with self._session_factory() as session:
                statement = select(AnamnesisEventModel).where(AnamnesisEventModel.process_id == process_id)
                result = session.execute(statement).scalar_one_or_none()
                if result is None:
                    return None
                return self._to_entity(result)
        except Exception as exc:
            raise PersistenceError(str(exc)) from exc

    def list_audit_events(self, page: int, page_size: int) -> tuple[list[dict[str, Any]], int]:
        try:
            offset = (page - 1) * page_size
            with self._session_factory() as session:
                total_statement = select(func.count()).select_from(AnamnesisAuditModel)
                total = session.execute(total_statement).scalar_one()

                statement = (
                    select(AnamnesisAuditModel)
                    .order_by(AnamnesisAuditModel.created_at.desc())
                    .offset(offset)
                    .limit(page_size)
                )
                results = session.execute(statement).scalars().all()
                return [self._audit_to_dict(item) for item in results], int(total)
        except Exception as exc:
            raise PersistenceError(str(exc)) from exc

    def get_audit_event_by_process_id(self, process_id: str) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                statement = (
                    select(AnamnesisAuditModel)
                    .where(AnamnesisAuditModel.process_id == process_id)
                    .order_by(AnamnesisAuditModel.created_at.desc())
                    .limit(1)
                )
                result = session.execute(statement).scalar_one_or_none()
                if result is None:
                    return None
                return self._audit_to_dict(result)
        except Exception as exc:
            raise PersistenceError(str(exc)) from exc
