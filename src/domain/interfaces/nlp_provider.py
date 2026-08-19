"""Port for providers that extract structured clinical labels from anonymized text."""

from abc import ABC, abstractmethod
from typing import Any


class NLPProviderInterface(ABC):
    """Contrato para proveedores que extraen etiquetas clínicas estructuradas."""

    @abstractmethod
    def extract_labels(self, anonymized_text: str, prompt_version: str, allowed_labels: list[str], timeout_seconds: int = 10) -> dict[str, Any]:
        """Recibe texto anonimizado y devuelve hallazgos normalizados para la aplicación."""
        raise NotImplementedError

    @abstractmethod
    def health_check(self, timeout_seconds: int = 2) -> bool:
        """Comprueba si el proveedor está disponible para recibir peticiones."""
        raise NotImplementedError
