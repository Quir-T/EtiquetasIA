"""Shared application helpers for anamnesis workflows."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any

from src.domain.entities.anamnesis_event import AnamnesisEvent, ProcessStatus
from src.domain.exceptions.domain_exceptions import PersistenceError
from src.domain.interfaces.repository import AnamnesisRepositoryInterface


@dataclass(slots=True)
class AnamnesisService:
    repository: AnamnesisRepositoryInterface

    def get_process(self, process_id: str) -> AnamnesisEvent | None:
        return self.repository.get_by_process_id(process_id)

    def persist_event(self, event: AnamnesisEvent) -> AnamnesisEvent:
        try:
            return self.repository.save(event)
        except PersistenceError as exc:
            raise PersistenceError(str(exc)) from exc

    @staticmethod
    def normalize_hallazgos(hallazgos: list[dict[str, Any]] | Any) -> list[dict[str, Any]]:
        if not isinstance(hallazgos, list):
            return []
        normalized: list[dict[str, Any]] = []
        for hallazgo in hallazgos:
            if not isinstance(hallazgo, dict):
                continue
            normalized.append(
                {
                    "etiqueta": hallazgo.get("etiqueta"),
                    "descripcion": hallazgo.get("descripcion"),
                    "confidence": hallazgo.get("confidence"),
                }
            )
        return normalized

    @staticmethod
    def elapsed_ms(started_at: float) -> int:
        return int((perf_counter() - started_at) * 1000)
