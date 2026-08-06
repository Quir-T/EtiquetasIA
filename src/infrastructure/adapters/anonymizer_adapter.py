""""Loads the configured anonymizer implementation dynamically and exposes it through the domain port."""

from __future__ import annotations

import importlib
import threading
from dataclasses import dataclass, field
from typing import Any

from src.domain.exceptions.domain_exceptions import AnonymizationError
from src.domain.interfaces.anonymizer import AnonymizerInterface
from src.config.settings import Settings

@dataclass(slots=True)
class ModuleAnonymizerAdapter(AnonymizerInterface):
    """Adapter que carga y cachea la implementacion configurada de anonymizer.

    La clase configurada via ANONYMIZER_MODULE/ANONYMIZER_CLASS se instancia
    una sola vez -lazy, en el primer anonymize() que llega- y se reutiliza en
    todos los requests siguientes. Esto es critico para implementaciones
    pesadas (ej. PresidioTransformerAnonymizer, que carga spaCy + un modelo
    Transformer completo en su __init__): instanciarla en cada request
    implicaria recargar el modelo por cada llamada.

    Este adapter ya se obtiene cacheado como singleton de proceso via
    @lru_cache en src.api.deps.get_anonymizer(), pero eso solo evitaba
    recrear el *adapter* (liviano, solo tiene settings). El anonymizer
    concreto se seguia recreando adentro de anonymize() en cada llamada;
    ese es el problema que resuelve el cacheo interno de esta clase.

    Thread-safety: se usa double-checked locking porque FastAPI puede atender
    requests concurrentes dentro del mismo proceso (via threadpool para
    codigo sync). Sin el lock, dos requests simultaneos durante el "cold
    start" podrian disparar dos instanciaciones del modelo en paralelo.
    """

    settings: Settings
    _anonymizer_instance: Any = field(default=None, init=False, repr=False, compare=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False, compare=False)

    def anonymize(self, text: str) -> str:
        anonymizer = self._get_or_create_anonymizer()
        try:
            return anonymizer.anonymize(text)
        except Exception as exc:
            raise AnonymizationError(str(exc)) from exc

    def _get_or_create_anonymizer(self) -> Any:
        # Fast path sin lock: una vez cacheada, no hay contencion en requests normales.
        if self._anonymizer_instance is not None:
            return self._anonymizer_instance

        with self._lock:
            # Re-chequear adentro del lock: otro thread pudo haber terminado
            # de instanciar el modelo mientras esperabamos.
            if self._anonymizer_instance is None:
                self._anonymizer_instance = self._load_anonymizer()
        return self._anonymizer_instance

    def _load_anonymizer(self) -> Any:
        module_path = getattr(self.settings, "anonymizer_module", "")
        class_name = getattr(self.settings, "anonymizer_class", "")
        if not module_path or not class_name:
            raise AnonymizationError("Anonymizer module is not configured")

        try:
            module = importlib.import_module(module_path)
            anonymizer_class = getattr(module, class_name)
            return anonymizer_class()
        except Exception as exc:
            raise AnonymizationError(str(exc)) from exc