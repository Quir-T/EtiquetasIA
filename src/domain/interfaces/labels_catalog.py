"""Port for reading and validating the closed set of allowed clinical labels."""

from abc import ABC, abstractmethod
from typing import Any


class LabelsCatalogInterface(ABC):
    @abstractmethod
    def get_allowed_labels(self) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    def get_catalog_version(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def validate_labels(self, labels: list[str]) -> bool:
        raise NotImplementedError

    @abstractmethod
    def get_full_catalog(self) -> dict[str, Any]:
        raise NotImplementedError
