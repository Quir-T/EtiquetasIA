"""Port for text anonymization implementations used by the application service."""

from abc import ABC, abstractmethod


class AnonymizerInterface(ABC):
    @abstractmethod
    def anonymize(self, text: str) -> str:
        raise NotImplementedError
