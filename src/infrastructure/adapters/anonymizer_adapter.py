"""Loads the configured anonymizer implementation dynamically and exposes it through the domain port."""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field

from src.domain.exceptions.domain_exceptions import AnonymizationError
from src.domain.interfaces.anonymizer import AnonymizerInterface
from src.config.settings import Settings


@dataclass(slots=True)
class ModuleAnonymizerAdapter(AnonymizerInterface):
    settings: Settings
    _instance: AnonymizerInterface | None = field(init=False, default=None, repr=False)

    def _get_anonymizer(self) -> AnonymizerInterface:
        if self._instance is not None:
            return self._instance

        module_path = getattr(self.settings, "anonymizer_module", "")
        class_name = getattr(self.settings, "anonymizer_class", "")
        if not module_path or not class_name:
            raise AnonymizationError("Anonymizer module is not configured")

        try:
            module = importlib.import_module(module_path)
            anonymizer_class = getattr(module, class_name)
            anonymizer = anonymizer_class()
        except Exception as exc:
            raise AnonymizationError(str(exc)) from exc

        if not isinstance(anonymizer, AnonymizerInterface):
            raise AnonymizationError(
                f"Configured anonymizer {module_path}.{class_name} must implement AnonymizerInterface"
            )

        self._instance = anonymizer
        return anonymizer

    def anonymize(self, text: str) -> str:
        try:
            return self._get_anonymizer().anonymize(text)
        except Exception as exc:
            raise AnonymizationError(str(exc)) from exc
