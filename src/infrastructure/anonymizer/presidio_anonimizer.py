"""Anonimizador de historias clínicas (Argentina) basado en Microsoft Presidio y Transformers.

Implementa el puerto AnonymizerInterface (anonymize(text) -> str) para poder
ser cargado dinámicamente por ModuleAnonymizerAdapter vía ANONYMIZER_MODULE /
ANONYMIZER_CLASS.

Dependencias necesarias (ver requirements.txt):
    presidio-analyzer, presidio-anonymizer, spacy, spacy-transformers, torch, transformers
    python -m spacy download es_core_news_lg

Cambios respecto a la version anterior (revision de falsos positivos, ver
conversacion de diseño):

1. Se remueve el "SpacyRecognizer" que Presidio agrega automaticamente al
   configurar el nlp_engine con es_core_news_lg. Ese recognizer usa el modelo
   NER generico de spaCy (entrenado en noticias/Wikipedia, nunca vio
   vocabulario clinico) con un ner_strength fijo de 0.85 para PERSON,
   LOCATION, ORGANIZATION y DATE_TIME. Al competir con el
   TransformerNerRecognizer (modelo BSC) sobre las mismas categorias,
   generaba la mayoria de los falsos positivos de LOCATION/ORGANIZATION
   (terminologia anatomica, siglas de laboratorio, diagnosticos, etc.).
   Se vuelve a agregar restringido SOLO a DATE_TIME, unica categoria donde
   su aporte es razonable y no compite con otro recognizer.

2. Se agrega un filtro de score diferenciado por categoria de entidad,
   aplicado despues de analyzer.analyze() y antes de anonymizer_engine.anonymize().
   LOCATION y ORGANIZATION requieren mayor confianza (mas permisivos con el
   texto: dejan pasar mas contenido clinico sin marcar). El resto de las
   categorias (PERSON, AR_DNI, AR_CUIT_CUIL, AR_TELEFONO,
   AR_HISTORIA_CLINICA, matriculas, afiliado) se mantiene agresivo, sin
   filtro adicional mas alla del score que ya calibra cada recognizer,
   porque el texto anonimizado se usa como input para un LLM externo
   (Gemini) y ahi se prefiere sobre-anonimizar antes que filtrar datos
   sensibles reales.

3. Se reescribe build_historia_clinica_recognizer(): los patrones anteriores
   (numero suelto de 5-6 digitos, o con separador de miles) matcheaban
   sistematicamente valores de laboratorio (recuentos de plaquetas/leucocitos
   tipo "162.000"). En este dominio (anamnesis del propio paciente que se
   esta procesando) no se referencian historias clinicas de terceros, asi
   que se prioriza precision sobre recall: el numero solo se considera
   AR_HISTORIA_CLINICA si esta anclado a la mencion explicita de la palabra
   clave (Historia Clinica / HC / N de historia), igual que ya se hace con
   matricula nacional/provincial y afiliado en este mismo archivo.

Nota: no se modifica nada relacionado a AR_DNI (build_dni_recognizer se deja
igual, incluido dni_sin_puntos sin anclaje a palabra clave), por decision
explicita: se prefiere mantenerlo agresivo y que capture cualquier numero de
7-8 digitos parecido a un DNI.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from transformers import pipeline

from presidio_analyzer import (
    AnalyzerEngine,
    Pattern,
    PatternRecognizer,
    EntityRecognizer,
    RecognizerResult,
)
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_analyzer.predefined_recognizers import SpacyRecognizer
from presidio_anonymizer import AnonymizerEngine

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# 0. Politica de umbrales por categoria (punto 2)
# --------------------------------------------------------------------------

# Categorias donde preferimos ser mas permisivos (exigir mayor confianza antes
# de anonimizar), porque son las que peor precision mostraron en la revision
# de casos y el destino final del texto es un LLM externo que se beneficia de
# mantener el maximo de contexto clinico posible.
ENTIDADES_PERMISIVAS = frozenset({"LOCATION", "ORGANIZATION"})

# Score minimo exigido SOLO para las entidades en ENTIDADES_PERMISIVAS.
# El resto de las entidades no pasa por este filtro adicional: se anonimizan
# con el score que ya les asigna su propio recognizer (comportamiento agresivo).
UMBRAL_PERMISIVO = 0.75


def _filtrar_por_politica_de_entidad(resultados: list[RecognizerResult]) -> list[RecognizerResult]:
    """Aplica el umbral diferenciado antes de pasar los resultados al AnonymizerEngine."""
    filtrados: list[RecognizerResult] = []
    for resultado in resultados:
        if resultado.entity_type in ENTIDADES_PERMISIVAS:
            if resultado.score >= UMBRAL_PERMISIVO:
                filtrados.append(resultado)
            continue
        filtrados.append(resultado)
    return filtrados


# --------------------------------------------------------------------------
# 1. Recognizer NER con Hugging Face
# --------------------------------------------------------------------------
class TransformerNerRecognizer(EntityRecognizer):
    """
    Usa el pipeline nativo de Hugging Face con aggregation_strategy="simple"
    para agrupar correctamente nombres compuestos (ej: Juan Pérez) y esquivar
    los problemas de mapeo interno de Presidio.
    """

    def __init__(self, model_name: str = "BSC-LT/roberta_model_for_anonimization", score_threshold: float = 0.4):
        self.label_map = {
            "PER": "PERSON",
            "LOC": "LOCATION",
            "ORG": "ORGANIZATION",
        }
        super().__init__(
            supported_entities=list(self.label_map.values()),
            name="TransformerNerRecognizer",
            supported_language="es",
        )
        self.score_threshold = score_threshold
        self._ner_pipeline = pipeline(
            task="token-classification",
            model=model_name,
            aggregation_strategy="simple",
        )

    def load(self) -> None:
        pass

    def analyze(self, text: str, entities: list[str], nlp_artifacts=None) -> list[RecognizerResult]:
        results = []
        for pred in self._ner_pipeline(text):
            if pred["score"] < self.score_threshold:
                continue

            entity_group = pred.get("entity_group")
            mapped_entity = self.label_map.get(entity_group)

            if not mapped_entity:
                continue
            if entities and mapped_entity not in entities:
                continue

            results.append(
                RecognizerResult(
                    entity_type=mapped_entity,
                    start=pred["start"],
                    end=pred["end"],
                    score=float(pred["score"]),
                )
            )
        return results


# --------------------------------------------------------------------------
# 2. Recognizers basados en patrones (Identificadores argentinos)
# --------------------------------------------------------------------------
def build_dni_recognizer() -> PatternRecognizer:
    # Sin cambios: se mantiene agresivo a pedido explicito.
    patterns = [
        Pattern(name="dni_con_puntos", regex=r"\b\d{1,2}\.\d{3}\.\d{3}\b", score=0.85),
        Pattern(name="dni_sin_puntos", regex=r"\b\d{7,8}\b", score=0.6),
    ]
    return PatternRecognizer(supported_entity="AR_DNI", patterns=patterns, context=["dni", "documento"], supported_language="es")


def build_cuit_cuil_recognizer() -> PatternRecognizer:
    pattern = Pattern(name="cuit_cuil", regex=r"\b(20|23|24|27|30|33|34)-?\d{8}-?\d\b", score=0.85)
    return PatternRecognizer(supported_entity="AR_CUIT_CUIL", patterns=[pattern], context=["cuit", "cuil"], supported_language="es")


def build_historia_clinica_recognizer() -> PatternRecognizer:
    """
    Reescrito (punto 3): el numero de historia clinica se ancla a la mencion
    explicita de la palabra clave, igual que matricula_nacional/provincial y
    afiliado en este mismo archivo. Se eliminan los patrones sueltos de
    numero (con y sin separador de miles) que matcheaban valores de
    laboratorio como "162.000" o "35.000".
    """
    pattern = Pattern(
        name="historia_clinica_anclada",
        regex=r"\b(?:Historia Cl[ií]nica|H\.?C\.?|Nro\.?\s*Historia Cl[ií]nica|N[º°]?\s*Historia Cl[ií]nica)\s*[:#\-Nº° ]*\s*(\d{3,8})\b",
        score=0.85,
    )
    return PatternRecognizer(
        supported_entity="AR_HISTORIA_CLINICA",
        patterns=[pattern],
        supported_language="es",
    )


def build_telefono_recognizer() -> PatternRecognizer:
    pattern = Pattern(name="telefono_ar", regex=r"\b(?:(?:011|15)[\s-]?)?\d{4}[\s-]?\d{4}\b", score=0.7)
    return PatternRecognizer(supported_entity="AR_TELEFONO", patterns=[pattern], context=["teléfono", "celular", "contacto"], supported_language="es")


def build_matricula_nacional_recognizer() -> PatternRecognizer:
    pattern = Pattern(
        name="mn",
        regex=r"\b(?:MN|M\.N\.|Matr[ií]cula Nacional(?:\s*[Nn][º°]?)?)\s*[:#Nº° ]*\s*(?:\d{1,3}(?:\.\d{3}){1,2}|\d{4,7})\b",
        score=0.85,
    )
    return PatternRecognizer(supported_entity="AR_MATRICULA_NACIONAL", patterns=[pattern], supported_language="es")


def build_matricula_provincial_recognizer() -> PatternRecognizer:
    pattern = Pattern(
        name="mp",
        regex=r"\b(?:MP|M\.P\.|Matr[ií]cula Provincial(?:\s*[Nn][º°]?)?)\s*[:#Nº° ]*\s*(?:\d{1,3}(?:\.\d{3}){1,2}|\d{4,7})\b",
        score=0.85,
    )
    return PatternRecognizer(supported_entity="AR_MATRICULA_PROVINCIAL", patterns=[pattern], supported_language="es")


def build_afiliado_recognizer() -> PatternRecognizer:
    pattern = Pattern(
        name="afiliado",
        regex=r"\b(?:Afiliad[oa]|N[º°]?\s*Afiliad[oa]|Nro\.?\s*Afiliad[oa]|Af\.)\s*[:#\- ]*\s*(?:\d{4,10})\b",
        score=0.85,
    )
    return PatternRecognizer(supported_entity="AR_AFILIADO", patterns=[pattern], supported_language="es")


def _cargar_gazetteer_establecimientos(config_path: Path | None = None) -> list[str]:
    """Carga y combina las dos fuentes del gazetteer de establecimientos de salud.

    'refes': nombres oficiales tal como figuran en REFES (datos.salud.gob.ar).
    'fugas_confirmadas_y_variantes': casos detectados en revision de casos que
    no coinciden textualmente con el nombre oficial (variantes abreviadas de
    uso clinico habitual, ej. "Hospital Penna" para "HOSPITAL INTERZONAL
    GENERAL DE AGUDOS DR. JOSE PENNA").

    Presidio's deny_list convierte automaticamente cada string en un patron
    regex anclado a limite de palabra e insensible a mayusculas/minusculas,
    por lo que no hace falta normalizar casing aca.
    """
    if config_path is None:
        config_path = Path(__file__).parent / "config" / "establecimientos.json"

    with config_path.open("r", encoding="utf-8") as handle:
        config = json.load(handle)

    refes = config.get("refes", [])
    variantes = config.get("fugas_confirmadas_y_variantes", [])

    # dedupe preservando orden, por si una variante ya viene cubierta por REFES.
    vistos: set[str] = set()
    combinado: list[str] = []
    for nombre in [*refes, *variantes]:
        nombre = nombre.strip()
        if nombre and nombre not in vistos:
            vistos.add(nombre)
            combinado.append(nombre)
    return combinado


def build_establecimientos_recognizer(config_path: Path | None = None) -> PatternRecognizer:
    """Gazetteer de establecimientos de salud vía deny_list (score 1.0).

    A diferencia de los demas recognizers de patrones, este no define un
    regex a mano: PatternRecognizer con deny_list arma internamente un
    patron por cada entrada de la lista, anclado a limite de palabra y
    case-insensitive. Al score 1.0 bypassa el UMBRAL_PERMISIVO (0.75) que
    aplica _filtrar_por_politica_de_entidad() sobre ORGANIZATION, que es la
    entidad a la que se asocia esta lista para que conviva con el resto
    del pipeline (TransformerNerRecognizer, SpacyRecognizer) sin duplicar
    logica de umbral.
    """
    establecimientos = _cargar_gazetteer_establecimientos(config_path)
    return PatternRecognizer(
        supported_entity="ORGANIZATION",
        deny_list=establecimientos,
        supported_language="es",
        name="EstablecimientosSaludRecognizer",
    )


def build_titulo_profesional_recognizer() -> PatternRecognizer:
    # Se unifica con "PERSON" para potenciar la IA
    pattern = Pattern(
        name="titulo",
        regex=r"\b(?:Dr\.?|Dra\.?|Prof\.?|Profa\.?|Lic\.?|Ing\.?|Arq\.?)\s+(?:[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+){0,2})",
        score=0.9,
    )
    return PatternRecognizer(supported_entity="PERSON", patterns=[pattern], supported_language="es")


# --------------------------------------------------------------------------
# 3. Ensamblado del AnalyzerEngine
# --------------------------------------------------------------------------
def build_analyzer() -> AnalyzerEngine:
    # Bloqueamos Presidio para que use SOLO spaCy en español (evita descargas en inglés)
    configuracion_nlp = {
        "nlp_engine_name": "spacy",
        "models": [{"lang_code": "es", "model_name": "es_core_news_lg"}],
    }

    provider = NlpEngineProvider(nlp_configuration=configuracion_nlp)
    nlp_engine = provider.create_engine()

    analyzer = AnalyzerEngine(
        nlp_engine=nlp_engine,
        supported_languages=["es"],
    )

    # Punto 1: Presidio agrega automaticamente un "SpacyRecognizer" atado a
    # es_core_news_lg (modelo NER generico entrenado en noticias/Wikipedia,
    # con ner_strength fijo de 0.85 para PERSON/LOCATION/ORGANIZATION/DATE_TIME).
    # Competia sin ninguna coordinacion con el TransformerNerRecognizer (BSC)
    # sobre las mismas tres categorias clinicas y era la principal fuente de
    # falsos positivos en LOCATION/ORGANIZATION (anatomia, siglas de
    # laboratorio, diagnosticos). Lo sacamos y lo volvemos a agregar
    # restringido solo a DATE_TIME, unica categoria donde no compite con
    # nadie y su aporte es razonable.
    analyzer.registry.remove_recognizer("SpacyRecognizer")
    analyzer.registry.add_recognizer(
        SpacyRecognizer(supported_language="es", supported_entities=["DATE_TIME"])
    )

    logger.info("Cargando modelo Transformer de Hugging Face para anonimizacion...")
    analyzer.registry.add_recognizer(TransformerNerRecognizer())

    # Inyectar reglas Regex
    analyzer.registry.add_recognizer(build_dni_recognizer())
    analyzer.registry.add_recognizer(build_cuit_cuil_recognizer())
    analyzer.registry.add_recognizer(build_telefono_recognizer())
    analyzer.registry.add_recognizer(build_historia_clinica_recognizer())
    analyzer.registry.add_recognizer(build_matricula_nacional_recognizer())
    analyzer.registry.add_recognizer(build_matricula_provincial_recognizer())
    analyzer.registry.add_recognizer(build_afiliado_recognizer())
    analyzer.registry.add_recognizer(build_titulo_profesional_recognizer())

    # Gazetteer de establecimientos de salud (REFES + fugas confirmadas y
    # variantes curadas). deny_list a score 1.0: bypassa el umbral de 0.75
    # que _filtrar_por_politica_de_entidad() aplica sobre ORGANIZATION.
    analyzer.registry.add_recognizer(build_establecimientos_recognizer())

    return analyzer


# --------------------------------------------------------------------------
# 4. Clase pública que cumple el contrato AnonymizerInterface
# --------------------------------------------------------------------------
class PresidioTransformerAnonymizer:
    """Anonimizador basado en Presidio + Transformer NER.

    Cumple el contrato usado por ModuleAnonymizerAdapter:
    - constructor sin argumentos obligatorios (se instancia como anonymizer_class())
    - expone anonymize(text: str) -> str

    NOTA DE RENDIMIENTO: __init__ carga spaCy + un modelo Transformer completo.
    Esta clase NO debe instanciarse por request; el caller (adapter) es
    responsable de cachear la instancia.
    """

    def __init__(self) -> None:
        self._analyzer = build_analyzer()
        self._anonymizer_engine = AnonymizerEngine()

    def anonymize(self, text: str) -> str:
        return self._anonimizar_texto_largo(text)

    def _anonimizar_texto_largo(self, texto_largo: str) -> str:
        """
        Divide el texto por saltos de línea para evitar el límite de 512 tokens
        del Transformer. Reconstruye el texto manteniendo el formato original.
        """
        fragmentos = texto_largo.split("\n")
        fragmentos_anonimizados = []

        for fragmento in fragmentos:
            if not fragmento.strip():
                fragmentos_anonimizados.append(fragmento)
                continue

            resultados = self._analyzer.analyze(text=fragmento, language="es")
            # Punto 2: umbral diferenciado por categoria antes de anonimizar.
            resultados = _filtrar_por_politica_de_entidad(resultados)
            resultado_anonimizado = self._anonymizer_engine.anonymize(
                text=fragmento,
                analyzer_results=resultados,
            )
            fragmentos_anonimizados.append(resultado_anonimizado.text)

        return "\n".join(fragmentos_anonimizados)