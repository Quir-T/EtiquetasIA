"""Loads the JSON catalog of allowed labels and caches it in memory."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.domain.interfaces.labels_catalog import LabelsCatalogInterface


@dataclass(slots=True)
class JsonLabelsCatalogLoader(LabelsCatalogInterface):
    catalog_path: Path
    _catalog_cache: dict[str, Any] | None = None

    def _load_catalog(self) -> dict[str, Any]:
        if self._catalog_cache is None:
            with self.catalog_path.open("r", encoding="utf-8") as handle:
                self._catalog_cache = json.load(handle)
        return self._catalog_cache

    def get_allowed_labels(self) -> list[str]:
        catalog = self._load_catalog()
        return [item["name"] for item in catalog.get("labels", [])]

    def get_catalog_version(self) -> str:
        return str(self._load_catalog().get("version", "unknown"))

    def validate_labels(self, labels: list[str]) -> bool:
        allowed = set(self.get_allowed_labels())
        return all(label in allowed for label in labels)

    def get_full_catalog(self) -> dict[str, Any]:
        return self._load_catalog()



def build_default_labels_catalog_loader() -> JsonLabelsCatalogLoader:
    return JsonLabelsCatalogLoader(catalog_path=Path(__file__).with_name("labels_catalog.json"))
