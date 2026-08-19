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
    """Helpers compartidos de servicio usados por los use cases de anamnesis.

    Este servicio centraliza el acceso a persistencia y las utilidades de
    normalización para que los use cases mantengan la lógica de orquestación
    más enfocada y fácil de probar.
    """

    repository: AnamnesisRepositoryInterface

    def get_process(self, process_id: str) -> AnamnesisEvent | None:
        """Recupera un evento de proceso por su identificador externo estable."""
        return self.repository.get_by_process_id(process_id)

    def persist_event(self, event: AnamnesisEvent) -> AnamnesisEvent:
        """Persiste un evento manteniendo tipadas las excepciones de persistencia."""
        try:
            return self.repository.save(event)
        except PersistenceError as exc:
            raise PersistenceError(str(exc)) from exc

    @staticmethod
    def normalize_hallazgos(hallazgos: list[dict[str, Any]] | Any) -> list[dict[str, Any]]:
        """Normaliza el payload de hallazgos a las claves esperadas por el esquema público.

        El comportamiento defensivo es intencional: los valores malformados se
        ignoran para que las respuestas de la API permanezcan estables incluso
        cuando los proveedores devuelvan JSON ruidoso.
        """
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
        """Convierte el tiempo transcurrido a milisegundos enteros."""
        return int((perf_counter() - started_at) * 1000)
