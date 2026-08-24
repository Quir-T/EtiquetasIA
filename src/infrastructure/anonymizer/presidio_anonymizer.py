"""Anonimizador de texto clínico basado en Microsoft Presidio y Transformers.

Implementa el puerto AnonymizerInterface (anonymize(text) -> str) para poder
ser cargado dinámicamente por ModuleAnonymizerAdapter vía ANONYMIZER_MODULE /
ANONYMIZER_CLASS.

Dependencias necesarias (ver requirements.txt):
    presidio-analyzer, presidio-anonymizer, spacy, spacy-transformers, torch, transformers
    python -m spacy download es_core_news_lg

Cambios respecto a la version anterior:

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
import re
from bisect import bisect_left, bisect_right
from pathlib import Path
from typing import Any

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

from src.domain.interfaces.anonymizer import AnonymizerInterface

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# 0. Politica de umbrales por categoria (punto 2)
# --------------------------------------------------------------------------

# Categorias donde se prefiere ser mas permisivo (exigir mayor confianza antes
# de anonimizar), porque son las que peor precision mostraron en la revision
# de casos y el destino final del texto es un LLM externo que se beneficia de
# mantener el maximo de contexto clinico posible.
ENTIDADES_PERMISIVAS = frozenset({"LOCATION", "ORGANIZATION"})

# Score minimo exigido SOLO para las entidades en ENTIDADES_PERMISIVAS.
# El resto de las entidades no pasa por este filtro adicional: se anonimizan
# con el score que ya les asigna su propio recognizer (comportamiento agresivo).
UMBRAL_PERMISIVO = 0.75

# Presupuesto operativo por chunk. Se deja margen por debajo del max_length
# del modelo para evitar cortes en el borde de contexto.
TOKEN_BUDGET = 480
TOKEN_OVERLAP = 24
SEPARADORES_PERSONA_MERGE = frozenset({" ", "'", "’", "-", "."})
VENTANA_TITULO_PERSONA = 20
PATRON_TITULO_CERCANO = re.compile(r"(?i)(?:\bdr\.?|\bdra\.?|\bprof\.?|\bprofa\.?|\blic\.?|\bing\.?|\barq\.?)\s*$")
PATRON_EXTENSION_NUMERO_CALLE = re.compile(
    r"(?i)^\s*(?:n[º°]?\s*|nro\.?\s*|#\s*)?\d{1,5}\b"
)


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
        Pattern(name="dni_con_puntos", regex=r"(?i)\b\d{1,2}[.-]\d{3}[.-]\d{3}\b", score=0.85),
        Pattern(name="dni_sin_puntos", regex=r"(?i)\b\d{7,8}\b", score=0.6),
    ]
    return PatternRecognizer(supported_entity="AR_DNI", patterns=patterns, context=["dni", "documento"], supported_language="es")


def build_cuit_cuil_recognizer() -> PatternRecognizer:
    pattern = Pattern(name="cuit_cuil", regex=r"(?i)\b(20|23|24|27|30|33|34)-?\d{8}-?\d\b", score=0.85)
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
        regex=r"(?i)\b(?:historia cl[ií]nica|h\.?c\.?|nro\.?\s*historia cl[ií]nica|n[º°]?\s*historia cl[ií]nica)\s*[:#\-nº° ]*\s*(\d{3,8})\b",
        score=0.85,
    )
    return PatternRecognizer(
        supported_entity="AR_HISTORIA_CLINICA",
        patterns=[pattern],
        supported_language="es",
    )


def build_telefono_recognizer() -> PatternRecognizer:
    pattern = Pattern(
        name="telefono_ar",
        regex=r"(?i)(?<!\d)(?:(?:\+?54[\s-]?)?(?:0?11|0?[2368]\d{1,3})[\s-]?\d{4}[\s-]?\d{4}|(?:\+?54[\s-]?)?15[\s-]?\d{4}[\s-]?\d{4})(?!\d)",
        score=0.7,
    )
    return PatternRecognizer(supported_entity="AR_TELEFONO", patterns=[pattern], context=["teléfono", "celular", "contacto"], supported_language="es")


def build_matricula_nacional_recognizer() -> PatternRecognizer:
    pattern = Pattern(
        name="mn",
        regex=r"(?i)\b(?:mn|m\.?n\.?|matr[ií]cula nacional(?:\s*n[º°]?)?)\s*[:#nº° ]*\s*(?:\d{1,3}(?:\.\d{3}){1,2}|\d{4,6})\b",
        score=0.85,
    )
    return PatternRecognizer(supported_entity="AR_MATRICULA_NACIONAL", patterns=[pattern], context=["matrícula", "nacional", "M.N", "mn"], supported_language="es")


def build_matricula_provincial_recognizer() -> PatternRecognizer:
    pattern = Pattern(
        name="mp",
        regex=r"(?i)\b(?:m\.?\s*p\.?|matr[ií]cula\s+provincial(?:\s*n[º°]?)?)\s*[:#nº° ]*\s*(?:\d{1,3}(?:\.\d{3}){1,2}|\d{4,6})\b",
        score=0.85,
    )
    return PatternRecognizer(supported_entity="AR_MATRICULA_PROVINCIAL", patterns=[pattern], context=["matrícula", "provincial", "M.P", "mp"], supported_language="es")


def build_afiliado_recognizer() -> PatternRecognizer:
    pattern = Pattern(
        name="afiliado",
        regex=r"(?i)\b(?:afiliad[oa]|n[º°]?\s*afiliad[oa]|nro\.?\s*afiliad[oa]|af\.)\s*[:#\- ]*\s*(?:\d{4,10})\b",
        score=0.85,
    )
    return PatternRecognizer(supported_entity="AR_AFILIADO", patterns=[pattern], supported_language="es")


def build_fecha_parcial_recognizer() -> PatternRecognizer:
    """Captura fechas parciales tipo 9/11 o 09/11, con día <= 31 y mes <= 12."""
    pattern = Pattern(
        name="fecha_parcial",
        regex=r"(?i)\b(?<!\d)(?:0?[1-9]|[12]\d|3[01])/(?:0?[1-9]|1[0-2])\b",
        score=0.8,
    )
    return PatternRecognizer(
        supported_entity="DATE_TIME",
        patterns=[pattern],
        context=["fecha", "consulta", "atención", "ingreso", "egreso", "alta", "nació", "nacido"],
        supported_language="es",
    )


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
        regex=r"(?i)\b(?:dr\.?|dra\.?|prof\.?|profa\.?|lic\.?|ing\.?|arq\.?)\s+(?:[a-záéíóúñ]+(?:[’'][a-záéíóúñ]+)*(?:\s+[a-záéíóúñ]+(?:[’'][a-záéíóúñ]+)*){0,2})",
        score=0.9,
    )
    return PatternRecognizer(supported_entity="PERSON", patterns=[pattern], supported_language="es")

def build_parentesco_person_recognizer() -> PatternRecognizer:
    # Cobertura especifica para parentesco + nombre en minusculas.
    pattern = Pattern(
        name="parentesco_persona",
        regex=r"(?i)(?<!\w)(?:madre|padre|hija|hijo|hermana|hermano|t[ií]a|t[ií]o|abuela|abuelo|esposa|esposo)\s+(?:de\s+)?(?!no\b|se\b|internad[oa]s?\b|estable\b|refiere\b|presenta\b|niega\b|con\b|sin\b|quien\b|que\b|del\b|la\b|el\b)[a-záéíóúñ]{2,}(?=$|[\s,.;:)\]])",
        score=0.85,
    )
    return PatternRecognizer(
        supported_entity="PERSON",
        patterns=[pattern],
        context=["familiar", "parentesco", "madre", "padre", "hermano", "hermana", "tío", "tía"],
        supported_language="es",
    )


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
    analyzer.registry.add_recognizer(build_fecha_parcial_recognizer())
    analyzer.registry.add_recognizer(build_titulo_profesional_recognizer())
    analyzer.registry.add_recognizer(build_parentesco_person_recognizer())

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
        self._sentence_segmenter = self._crear_segmentador_oraciones_liviano()
        self._sentence_model = self._analyzer.nlp_engine.nlp.get("es")
        self._tokenizer = self._obtener_tokenizer_transformer()

    def anonymize(self, text: str) -> str:
        return self._anonimizar_texto_largo(text)

    @staticmethod
    def _crear_segmentador_oraciones_liviano() -> Any | None:
        try:
            import spacy

            nlp = spacy.blank("es")
            nlp.add_pipe("sentencizer")
            return nlp
        except Exception:
            return None

    def _obtener_tokenizer_transformer(self) -> Any | None:
        for recognizer in self._analyzer.registry.recognizers:
            ner_pipeline = getattr(recognizer, "_ner_pipeline", None)
            tokenizer = getattr(ner_pipeline, "tokenizer", None)
            if tokenizer is not None:
                return tokenizer
        return None

    def _contar_tokens(self, text: str) -> int:
        if not text:
            return 0
        if self._tokenizer is None:
            return len(text.split())
        return len(
            self._tokenizer(
                text,
                add_special_tokens=False,
                truncation=False,
                verbose=False,
            )["input_ids"]
        )

    def _segmentar_oraciones(self, text: str) -> list[tuple[int, int]]:
        if not text.strip():
            return []

        if self._sentence_segmenter is not None:
            doc = self._sentence_segmenter(text)
            spans = [(sent.start_char, sent.end_char) for sent in doc.sents if sent.end_char > sent.start_char]
            if spans:
                return spans

        if self._sentence_model is None:
            return [(0, len(text))]

        doc = self._sentence_model(text)
        spans = [(sent.start_char, sent.end_char) for sent in doc.sents if sent.end_char > sent.start_char]
        if spans:
            return spans
        return [(0, len(text))]

    def _obtener_offsets_globales_tokens(self, text: str) -> list[tuple[int, int]]:
        if self._tokenizer is None or not text:
            return []

        encoded = self._tokenizer(
            text,
            add_special_tokens=False,
            truncation=False,
            verbose=False,
            return_offsets_mapping=True,
        )
        offsets = encoded.get("offset_mapping", [])
        return [(start, end) for start, end in offsets if end > start]

    @staticmethod
    def _contar_tokens_en_span(
        start: int,
        end: int,
        token_starts: list[int],
        token_ends: list[int],
    ) -> int:
        if start >= end or not token_starts:
            return 0
        token_ini = bisect_right(token_ends, start)
        token_fin = bisect_left(token_starts, end)
        return max(0, token_fin - token_ini)

    @staticmethod
    def _trocear_span_por_tokens_globales(
        start: int,
        end: int,
        token_starts: list[int],
        token_ends: list[int],
    ) -> list[tuple[int, int]]:
        if start >= end or not token_starts:
            return []

        primer_token = bisect_right(token_ends, start)
        ultimo_token_excl = bisect_left(token_starts, end)
        if primer_token >= ultimo_token_excl:
            return [(start, end)]

        paso = max(1, TOKEN_BUDGET - TOKEN_OVERLAP)
        chunks: list[tuple[int, int]] = []
        idx = primer_token
        while idx < ultimo_token_excl:
            fin_idx = min(idx + TOKEN_BUDGET, ultimo_token_excl)
            ini_char = token_starts[idx]
            fin_char = token_ends[fin_idx - 1]

            if fin_char <= ini_char:
                idx += 1
                continue

            chunks.append((ini_char, fin_char))
            if fin_idx >= ultimo_token_excl:
                break
            idx += paso

        return chunks

    def _trocear_por_tokens(self, text: str, start: int, end: int) -> list[tuple[int, int]]:
        if start >= end:
            return []

        fragmento = text[start:end]
        if self._tokenizer is None:
            # Fallback conservador si no hay tokenizer disponible.
            ancho = 1200
            solape = 150
            chunks: list[tuple[int, int]] = []
            i = start
            while i < end:
                j = min(i + ancho, end)
                chunks.append((i, j))
                if j >= end:
                    break
                i = max(i + 1, j - solape)
            return chunks

        encoded = self._tokenizer(
            fragmento,
            add_special_tokens=False,
            truncation=False,
            verbose=False,
            return_offsets_mapping=True,
        )
        offsets = encoded.get("offset_mapping", [])
        if not offsets:
            return [(start, end)]

        chunks = []
        paso = max(1, TOKEN_BUDGET - TOKEN_OVERLAP)
        idx = 0
        total = len(offsets)
        while idx < total:
            fin_idx = min(idx + TOKEN_BUDGET, total)
            ini_char = offsets[idx][0]
            fin_char = offsets[fin_idx - 1][1]

            if fin_char <= ini_char:
                idx += 1
                continue

            chunks.append((start + ini_char, start + fin_char))
            if fin_idx >= total:
                break
            idx += paso

        return chunks

    def _construir_chunks(self, text: str) -> list[tuple[int, int]]:
        spans = self._segmentar_oraciones(text)
        if not spans:
            return []

        offsets_globales = self._obtener_offsets_globales_tokens(text)
        token_starts = [start for start, _ in offsets_globales]
        token_ends = [end for _, end in offsets_globales]

        if token_starts:
            return self._construir_chunks_con_offsets_tokens(spans, token_starts, token_ends)
        return self._construir_chunks_sin_offsets_tokens(text, spans)

    def _construir_chunks_con_offsets_tokens(
        self,
        spans: list[tuple[int, int]],
        token_starts: list[int],
        token_ends: list[int],
    ) -> list[tuple[int, int]]:
        chunks: list[tuple[int, int]] = []
        chunk_start: int | None = None
        chunk_end: int | None = None
        chunk_tokens = 0

        for sent_start, sent_end in spans:
            sent_tokens = self._contar_tokens_en_span(sent_start, sent_end, token_starts, token_ends)

            if chunk_start is None:
                if sent_tokens > TOKEN_BUDGET:
                    chunks.extend(
                        self._trocear_span_por_tokens_globales(sent_start, sent_end, token_starts, token_ends)
                    )
                    continue
                chunk_start = sent_start
                chunk_end = sent_end
                chunk_tokens = sent_tokens
                continue

            if chunk_tokens + sent_tokens <= TOKEN_BUDGET:
                chunk_end = sent_end
                chunk_tokens += sent_tokens
                continue

            chunks.append((chunk_start, chunk_end))

            if sent_tokens > TOKEN_BUDGET:
                chunks.extend(
                    self._trocear_span_por_tokens_globales(sent_start, sent_end, token_starts, token_ends)
                )
                chunk_start = None
                chunk_end = None
                chunk_tokens = 0
            else:
                chunk_start = sent_start
                chunk_end = sent_end
                chunk_tokens = sent_tokens

        if chunk_start is not None and chunk_end is not None:
            chunks.append((chunk_start, chunk_end))

        return chunks

    def _construir_chunks_sin_offsets_tokens(
        self,
        text: str,
        spans: list[tuple[int, int]],
    ) -> list[tuple[int, int]]:
        # Fallback si no se puede recuperar offsets del tokenizer.
        chunks: list[tuple[int, int]] = []
        chunk_start: int | None = None
        chunk_end: int | None = None

        for sent_start, sent_end in spans:
            sent_tokens = self._contar_tokens(text[sent_start:sent_end])

            if chunk_start is None:
                if sent_tokens > TOKEN_BUDGET:
                    chunks.extend(self._trocear_por_tokens(text, sent_start, sent_end))
                    continue
                chunk_start = sent_start
                chunk_end = sent_end
                continue

            candidato_fin = sent_end
            candidato_tokens = self._contar_tokens(text[chunk_start:candidato_fin])
            if candidato_tokens <= TOKEN_BUDGET:
                chunk_end = candidato_fin
                continue

            chunks.append((chunk_start, chunk_end))

            if sent_tokens > TOKEN_BUDGET:
                chunks.extend(self._trocear_por_tokens(text, sent_start, sent_end))
                chunk_start = None
                chunk_end = None
            else:
                chunk_start = sent_start
                chunk_end = sent_end

        if chunk_start is not None and chunk_end is not None:
            chunks.append((chunk_start, chunk_end))

        return chunks

    @staticmethod
    def _deduplicar_resultados(resultados: list[RecognizerResult]) -> list[RecognizerResult]:
        dedupe: dict[tuple[str, int, int], RecognizerResult] = {}
        for r in resultados:
            if r.end <= r.start:
                continue
            key = (r.entity_type, r.start, r.end)
            previo = dedupe.get(key)
            if previo is None or r.score > previo.score:
                dedupe[key] = r
        return sorted(dedupe.values(), key=lambda r: (r.start, r.end, -r.score))

    @staticmethod
    def _tiene_titulo_profesional_cercano(texto: str, start: int) -> bool:
        inicio = max(0, start - VENTANA_TITULO_PERSONA)
        contexto = texto[inicio:start]
        return bool(PATRON_TITULO_CERCANO.search(contexto))

    @staticmethod
    def _es_merge_persona_valido(izquierda: RecognizerResult, derecha: RecognizerResult, texto: str) -> bool:
        if izquierda.entity_type != "PERSON" or derecha.entity_type != "PERSON":
            return False
        if derecha.start < izquierda.end:
            return False

        separador = texto[izquierda.end : derecha.start]
        if len(separador) > 3:
            return False
        if any(char in "\n,:;" for char in separador):
            return False
        if any(char not in SEPARADORES_PERSONA_MERGE for char in separador):
            return False

        texto_izquierda = texto[izquierda.start : izquierda.end].strip(" .'’-")
        texto_derecha = texto[derecha.start : derecha.end].strip(" .'’-")
        if len(texto_izquierda) < 1 or len(texto_derecha) < 2:
            return False

        if len(texto_izquierda) == 1 and not PresidioTransformerAnonymizer._tiene_titulo_profesional_cercano(
            texto,
            izquierda.start,
        ):
            return False

        return True

    def _fusionar_personas_fragmentadas(self, texto: str, resultados: list[RecognizerResult]) -> list[RecognizerResult]:
        if not resultados:
            return resultados

        ordenados = sorted(resultados, key=lambda r: (r.start, r.end, -r.score))
        fusionados: list[RecognizerResult] = []
        actual = ordenados[0]

        for candidato in ordenados[1:]:
            if self._es_merge_persona_valido(actual, candidato, texto):
                actual = RecognizerResult(
                    entity_type="PERSON",
                    start=actual.start,
                    end=candidato.end,
                    score=max(actual.score, candidato.score),
                    analysis_explanation=actual.analysis_explanation,
                    recognition_metadata=actual.recognition_metadata,
                )
                continue

            fusionados.append(actual)
            actual = candidato

        fusionados.append(actual)
        return fusionados

    @staticmethod
    def _es_merge_location_valido(izquierda: RecognizerResult, derecha: RecognizerResult, texto: str) -> bool:
        if izquierda.entity_type != "LOCATION" or derecha.entity_type != "LOCATION":
            return False
        if derecha.start < izquierda.end:
            return True

        separador = texto[izquierda.end : derecha.start]
        if len(separador) > 20:
            return False
        if any(char in "\n;:" for char in separador):
            return False
        if "." in separador:
            return False
        return True

    @staticmethod
    def _extender_location_con_numero(texto: str, resultado: RecognizerResult) -> RecognizerResult:
        if resultado.entity_type != "LOCATION" or resultado.end >= len(texto):
            return resultado

        match = PATRON_EXTENSION_NUMERO_CALLE.match(texto[resultado.end : resultado.end + 20])
        if not match:
            return resultado

        return RecognizerResult(
            entity_type=resultado.entity_type,
            start=resultado.start,
            end=resultado.end + match.end(),
            score=resultado.score,
            analysis_explanation=resultado.analysis_explanation,
            recognition_metadata=resultado.recognition_metadata,
        )

    def _fusionar_locations_y_numero(self, texto: str, resultados: list[RecognizerResult]) -> list[RecognizerResult]:
        if not resultados:
            return resultados

        ordenados = sorted(resultados, key=lambda r: (r.start, r.end, -r.score))
        fusionados: list[RecognizerResult] = []
        actual = ordenados[0]

        for candidato in ordenados[1:]:
            if self._es_merge_location_valido(actual, candidato, texto):
                actual = RecognizerResult(
                    entity_type="LOCATION",
                    start=actual.start,
                    end=max(actual.end, candidato.end),
                    score=max(actual.score, candidato.score),
                    analysis_explanation=actual.analysis_explanation,
                    recognition_metadata=actual.recognition_metadata,
                )
                continue

            if actual.entity_type == "LOCATION":
                actual = self._extender_location_con_numero(texto, actual)
            fusionados.append(actual)
            actual = candidato

        if actual.entity_type == "LOCATION":
            actual = self._extender_location_con_numero(texto, actual)
        fusionados.append(actual)

        return fusionados

    def _anonimizar_texto_largo(self, texto_largo: str) -> str:
        """Anonimiza por chunks de oraciones respetando un presupuesto de tokens."""
        if not texto_largo.strip():
            return texto_largo

        chunks = self._construir_chunks(texto_largo)
        if not chunks:
            return texto_largo

        resultados_globales: list[RecognizerResult] = []
        for start, end in chunks:
            fragmento = texto_largo[start:end]
            if not fragmento.strip():
                continue

            resultados = self._analyzer.analyze(text=fragmento, language="es")
            resultados = _filtrar_por_politica_de_entidad(resultados)
            for r in resultados:
                resultados_globales.append(
                    RecognizerResult(
                        entity_type=r.entity_type,
                        start=r.start + start,
                        end=r.end + start,
                        score=r.score,
                        analysis_explanation=r.analysis_explanation,
                        recognition_metadata=r.recognition_metadata,
                    )
                )

        resultados_globales = self._deduplicar_resultados(resultados_globales)
        resultados_globales = self._fusionar_personas_fragmentadas(texto_largo, resultados_globales)
        resultados_globales = self._fusionar_locations_y_numero(texto_largo, resultados_globales)
        resultados_globales = self._deduplicar_resultados(resultados_globales)
        if not resultados_globales:
            return texto_largo

        resultado_anonimizado = self._anonymizer_engine.anonymize(
            text=texto_largo,
            analyzer_results=resultados_globales,
        )
        return resultado_anonimizado.text