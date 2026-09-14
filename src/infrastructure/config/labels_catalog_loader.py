"""Loads the labels catalog at startup and serves it from in-memory runtime cache."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text

from src.config.settings import Settings
from src.domain.interfaces.labels_catalog import LabelsCatalogInterface


logger = logging.getLogger(__name__)
_runtime_catalog_cache: dict[str, Any] | None = None
_VERSION_PATTERN = re.compile(r"^v(?P<counter>\d+)_")


def _resolve_snapshot_path(settings: Settings) -> Path:
    configured = Path(settings.labels_catalog_snapshot_path).expanduser()
    return configured if configured.is_absolute() else Path.cwd() / configured


def _resolve_history_path(snapshot_path: Path) -> Path:
    return snapshot_path.with_name(f"{snapshot_path.stem}_history.jsonl")


def _normalize_catalog_labels(labels: list[dict[str, Any]]) -> list[dict[str, str]]:
    normalized = _normalize_labels(labels)
    return sorted(normalized, key=lambda item: (item["name"], item["description"]))


def _catalog_labels_signature(labels: list[dict[str, Any]]) -> list[dict[str, str]]:
    return _normalize_catalog_labels(labels)


def _read_last_history_entry(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None

    last_non_empty_line = ""
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                last_non_empty_line = line

    if not last_non_empty_line:
        return None
    return json.loads(last_non_empty_line)


def _read_catalog_file(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_catalog_file(path: Path, catalog: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(catalog, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _append_catalog_history(path: Path, catalog: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    history_entry = {
        "version": catalog.get("version", "unknown"),
        "last_updated": catalog.get("last_updated"),
        "source": catalog.get("source", "unknown"),
        "labels_count": len(catalog.get("labels", [])),
        "labels": catalog.get("labels", []),
    }

    last_entry = _read_last_history_entry(path)
    if last_entry is not None:
        same_source = str(last_entry.get("source", "")) == str(history_entry["source"])
        same_labels = _catalog_labels_signature(list(last_entry.get("labels", []))) == _catalog_labels_signature(list(history_entry["labels"]))
        if same_source and same_labels:
            logger.info(
                "Labels catalog history unchanged; skipping append for version=%s",
                history_entry["version"],
            )
            return

    with path.open("a", encoding="utf-8") as handle:
        json.dump(history_entry, handle, ensure_ascii=False)
        handle.write("\n")


def _normalize_labels(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for row in rows:
        name = str(row.get("name", "")).strip()
        if not name:
            continue
        description = str(row.get("description", "")).strip()
        normalized.append({"name": name, "description": description})
    return normalized


def _ensure_not_empty(labels: list[dict[str, str]]) -> None:
    if not labels:
        raise ValueError("Labels catalog cannot be empty")


def _version_counter_from_catalog(catalog: dict[str, Any]) -> int:
    version = str(catalog.get("version", "")).strip()
    if not version:
        return 0
    match = _VERSION_PATTERN.match(version)
    if not match:
        return 0
    return int(match.group("counter"))


def _build_catalog(labels: list[dict[str, str]], previous_counter: int, source: str) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y%m%dT%H%M%SZ")
    return {
        "version": f"v{previous_counter + 1}_{timestamp}",
        "last_updated": now.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "source": source,
        "labels": labels,
    }


def _load_labels_from_external_db(settings: Settings) -> list[dict[str, str]]:
    if not settings.labels_catalog_external_dsn:
        raise ValueError("LABELS_CATALOG_EXTERNAL_DSN is empty")
    if not settings.labels_catalog_external_query.strip():
        raise ValueError("LABELS_CATALOG_EXTERNAL_QUERY is empty")

    engine = create_engine(settings.labels_catalog_external_dsn, pool_pre_ping=True, future=True)
    with engine.connect() as connection:
        result = connection.execute(text(settings.labels_catalog_external_query))
        rows = [dict(row._mapping) for row in result]

    normalized_rows = _normalize_labels(rows)
    _ensure_not_empty(normalized_rows)
    return normalized_rows


def _load_catalog_from_json(path: Path) -> dict[str, Any]:
    catalog = _read_catalog_file(path)
    labels = _normalize_labels(list(catalog.get("labels", [])))
    _ensure_not_empty(labels)
    catalog["labels"] = labels
    if "version" not in catalog:
        catalog["version"] = "unknown"
    if "last_updated" not in catalog:
        catalog["last_updated"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return catalog


def initialize_runtime_labels_catalog(settings: Settings) -> None:
    """Bootstraps the runtime labels catalog from external DB with JSON fallback."""
    global _runtime_catalog_cache

    snapshot_path = _resolve_snapshot_path(settings)
    if settings.labels_catalog_source == "json":
        catalog = _load_catalog_from_json(snapshot_path)
        _runtime_catalog_cache = catalog
        logger.info(
            "Labels catalog loaded from JSON snapshot: version=%s labels=%s",
            catalog.get("version"),
            len(catalog.get("labels", [])),
        )
        return

    previous_counter = 0
    if snapshot_path.exists():
        try:
            previous_catalog = _read_catalog_file(snapshot_path)
            previous_counter = _version_counter_from_catalog(previous_catalog)
        except Exception:
            previous_counter = 0

    try:
        labels = _load_labels_from_external_db(settings)
        catalog = _build_catalog(labels=labels, previous_counter=previous_counter, source="external_db")
        _write_catalog_file(snapshot_path, catalog)
        _append_catalog_history(_resolve_history_path(snapshot_path), catalog)
        _runtime_catalog_cache = catalog
        logger.info(
            "Labels catalog loaded from external DB: version=%s labels=%s snapshot=%s history=%s",
            catalog.get("version"),
            len(catalog.get("labels", [])),
            snapshot_path,
            _resolve_history_path(snapshot_path),
        )
        return
    except Exception as exc:
        logger.error("Could not load labels from external DB. Falling back to snapshot JSON. Error: %s", exc)

    catalog = _load_catalog_from_json(snapshot_path)
    _runtime_catalog_cache = catalog
    logger.warning(
        "Labels catalog loaded from fallback JSON snapshot: version=%s labels=%s snapshot=%s",
        catalog.get("version"),
        len(catalog.get("labels", [])),
        snapshot_path,
    )


def _get_runtime_catalog() -> dict[str, Any]:
    if _runtime_catalog_cache is None:
        raise RuntimeError("Labels catalog runtime cache is not initialized")
    return _runtime_catalog_cache


@dataclass(slots=True)
class RuntimeLabelsCatalogLoader(LabelsCatalogInterface):
    def get_allowed_labels(self) -> list[str]:
        catalog = _get_runtime_catalog()
        return [str(item["name"]) for item in catalog.get("labels", [])]

    def get_catalog_version(self) -> str:
        return str(_get_runtime_catalog().get("version", "unknown"))

    def validate_labels(self, labels: list[str]) -> bool:
        allowed = set(self.get_allowed_labels())
        return all(label in allowed for label in labels)

    def get_full_catalog(self) -> dict[str, Any]:
        return _get_runtime_catalog()


def build_default_labels_catalog_loader() -> RuntimeLabelsCatalogLoader:
    """Backward-compatible alias kept for existing imports."""
    return RuntimeLabelsCatalogLoader()


def build_runtime_labels_catalog_loader() -> RuntimeLabelsCatalogLoader:
    return RuntimeLabelsCatalogLoader()
