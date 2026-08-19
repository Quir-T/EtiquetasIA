"""Port for text anonymization implementations used by the application service."""

from abc import ABC, abstractmethod


class AnonymizerInterface(ABC):
    """Contrato para implementaciones que anonimizan texto clínico."""

    @abstractmethod
    def anonymize(self, text: str) -> str:
        """Devuelve una versión anonimizada del texto recibido."""
        raise NotImplementedError
