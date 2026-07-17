"""Provides access to the allowed label catalog and filters extracted labels against it."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.domain.interfaces.labels_catalog import LabelsCatalogInterface


@dataclass(slots=True)
class LabelsCatalogService:
    labels_catalog: LabelsCatalogInterface

    def get_catalog(self) -> dict[str, Any]:
        return self.labels_catalog.get_full_catalog()

    def get_allowed_labels(self) -> list[str]:
        return self.labels_catalog.get_allowed_labels()

    def get_catalog_version(self) -> str:
        return self.labels_catalog.get_catalog_version()

    def validate_and_filter_labels(self, labels: list[dict[str, Any]]) -> list[dict[str, Any]]:
        allowed_labels = set(self.get_allowed_labels())
        filtered_labels: list[dict[str, Any]] = []
        for label in labels:
            name = str(label.get("name", "")).strip()
            if not name or name not in allowed_labels:
                continue
            filtered_labels.append({"name": name, "confidence": label.get("confidence")})
        return filtered_labels

    def validate_and_filter_hallazgos(self, hallazgos: list[dict[str, Any]]) -> list[dict[str, str]]:
        allowed_labels = set(self.get_allowed_labels())
        filtered_hallazgos: list[dict[str, str]] = []
        for hallazgo in hallazgos:
            etiqueta = str(hallazgo.get("etiqueta", "")).strip()
            descripcion = str(hallazgo.get("descripcion", "")).strip()
            if not etiqueta or etiqueta not in allowed_labels:
                continue
            if not descripcion:
                continue
            filtered_hallazgos.append({"etiqueta": etiqueta, "descripcion": descripcion})
        return filtered_hallazgos
