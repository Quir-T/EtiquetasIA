"""Legacy spaCy-based anonymizer that detects and masks sensitive entities using local rules and patterns."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import spacy


class LegacySpacyAnonymizer:
    """Anonimizador migrado desde el proyecto anterior.

    Contrato compatible con el adapter actual del proyecto:
    - expone anonymize(text) -> str
    - mantiene la salida extendida via process_text(text)
    """

    def __init__(self, config_dir: Path | None = None, model_name: str = "es_core_news_lg") -> None:
        base_dir = Path(__file__).parent
        self.config_dir = config_dir or (base_dir / "config")

        try:
            self.nlp = spacy.load(model_name)
        except OSError as exc:
            raise RuntimeError(
                "Modelo 'es_core_news_lg' no encontrado. Instalar con: python -m spacy download es_core_news_lg"
            ) from exc

        self._load_configuration()

    def _load_json_config(self, filename: str) -> dict[str, Any]:
        path = self.config_dir / filename
        try:
            with open(path, "r", encoding="utf-8") as file:
                return json.load(file)
        except FileNotFoundError as exc:
            raise FileNotFoundError(f"No se encontro el archivo de configuracion: {path}") from exc
        except json.JSONDecodeError as exc:
            raise ValueError(f"El archivo {path} no es un JSON valido") from exc

    @staticmethod
    def _required_field(config: dict[str, Any], field: str, filename: str) -> Any:
        if field not in config:
            raise ValueError(f"Falta el campo obligatorio '{field}' en {filename}")
        return config[field]

    def _load_configuration(self) -> None:
        config_ignore = self._load_json_config("ignorar.json")
        self.ignore_words = set(self._required_field(config_ignore, "palabras", "ignorar.json"))

        config_params = self._load_json_config("parametros.json")
        self.valid_labels = set(self._required_field(config_params, "labels_validas", "parametros.json"))
        self.min_per_length = int(self._required_field(config_params, "min_longitud_per", "parametros.json"))
        self.reject_lowercase = bool(self._required_field(config_params, "rechazar_todo_minusculas", "parametros.json"))
        self.person_contexts = set(self._required_field(config_params, "contextos_persona", "parametros.json"))
        self.valid_org_terms = set(self._required_field(config_params, "terminos_org_validos", "parametros.json"))
        self.exclude_medical_terms = set(self._required_field(config_params, "terminos_medicos_excluir", "parametros.json"))
        self.exclude_person_terms = set(config_params.get("terminos_per_excluir", []))

        config_force = self._load_json_config("anonimizar.json")
        self.force_words = self._required_field(config_force, "palabras", "anonimizar.json")

        config_patterns = self._load_json_config("patrones.json")
        pattern_definitions = self._required_field(config_patterns, "patrones", "patrones.json")
        self.compiled_patterns: list[dict[str, Any]] = []

        for item in pattern_definitions:
            try:
                self.compiled_patterns.append(
                    {
                        "name": item.get("name"),
                        "label": item.get("label"),
                        "regex": re.compile(item.get("pattern", ""), re.IGNORECASE),
                    }
                )
            except re.error as exc:
                raise ValueError(f"Error compilando patron {item.get('name')}: {exc}") from exc

    def _detect_patterns(self, text: str) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for item in self.compiled_patterns:
            for match in item["regex"].finditer(text):
                start, end = match.span(0)
                if start == end:
                    continue
                results.append(
                    {
                        "texto": match.group(0),
                        "etiqueta": item["label"],
                        "start": start,
                        "end": end,
                        "origen": "patron",
                    }
                )
        return results

    @staticmethod
    def _is_excluded(text: str, excluded_words_lower: set[str]) -> bool:
        key = text.lower().strip()
        if not key:
            return False
        return key in excluded_words_lower

    def _context_priority(self, doc: Any, entity: Any) -> int:
        start = max(0, entity.start_char - 40)
        end = min(len(doc.text), entity.end_char + 40)
        context = doc.text[start:end].lower()
        if any(term in context for term in self.person_contexts):
            return 2
        return 1

    def _is_valid_spacy_entity(self, ent: Any, doc: Any, excluded_words_lower: set[str]) -> tuple[bool, bool, int]:
        entity_text = ent.text.strip()
        if not entity_text:
            return False, False, 0

        if ent.label_ not in self.valid_labels:
            return False, False, 0

        if len(entity_text) < self.min_per_length and ent.label_ == "PER":
            return False, False, 0

        if self._is_excluded(entity_text, excluded_words_lower):
            return False, False, 0

        if entity_text.lower() in self.exclude_medical_terms:
            return False, False, 0

        if ent.label_ == "PER":
            if "\r" in entity_text or "\n" in entity_text:
                return False, False, 0

            tokens = [token for token in ent]
            clean_tokens = [re.sub(r"[^A-Za-zÁÉÍÓÚÜÑáéíóúüñ]", "", token.text).lower() for token in tokens]

            if any(token in self.exclude_person_terms for token in clean_tokens if token):
                return False, False, 0

            if any(token in {"h", "hs"} for token in clean_tokens if token):
                return False, False, 0

            if self.reject_lowercase and entity_text == entity_text.lower():
                return False, False, 0

            propn_count = sum(1 for token in tokens if token.pos_ == "PROPN")
            if propn_count < 2:
                return False, False, 0

            if any(len(token.text) < 2 for token in tokens):
                return False, False, 0

            priority = self._context_priority(doc, ent)
            return True, False, priority

        if ent.label_ == "ORG":
            text_lower = entity_text.lower()
            if any(term in text_lower for term in self.valid_org_terms):
                priority = self._context_priority(doc, ent)
                return True, False, priority

            if re.fullmatch(r"[A-ZÁÉÍÓÚÑ]{2,8}", entity_text):
                return False, True, 0

        return False, False, 0

    def _anonymize_with_entities(self, text: str, ignore_words: set[str] | None = None) -> tuple[str, list[dict[str, Any]]]:
        if ignore_words is None:
            ignore_words = self.ignore_words

        excluded_words_lower = {word.lower() for word in ignore_words}
        anonymized_text = text
        entities_info: list[dict[str, Any]] = []
        anonymized_spans: set[tuple[int, int]] = set()

        detected_patterns = self._detect_patterns(text)

        forced_words: list[dict[str, Any]] = []
        for word, label in self.force_words.items():
            idx = 0
            while True:
                idx = text.lower().find(word.lower(), idx)
                if idx == -1:
                    break

                start_ok = idx == 0 or not text[idx - 1].isalnum()
                end_ok = idx + len(word) >= len(text) or not text[idx + len(word)].isalnum()

                if start_ok and end_ok:
                    forced_words.append(
                        {
                            "texto": word,
                            "etiqueta": label,
                            "start": idx,
                            "end": idx + len(word),
                            "origen": "obligatoria",
                        }
                    )

                idx += 1

        filtered_forced_words: list[dict[str, Any]] = []
        for forced_word in forced_words:
            inside_pattern = False
            for pattern in detected_patterns:
                if not (forced_word["end"] <= pattern["start"] or forced_word["start"] >= pattern["end"]):
                    inside_pattern = True
                    break
            if not inside_pattern:
                filtered_forced_words.append(forced_word)

        forced_words = filtered_forced_words

        doc = self.nlp(text)
        valid_entities: list[dict[str, Any]] = []
        for ent in doc.ents:
            if ent.label_ not in self.valid_labels:
                continue

            accepted, ambiguous, priority = self._is_valid_spacy_entity(ent, doc, excluded_words_lower)
            if accepted and not ambiguous:
                valid_entities.append(
                    {
                        "texto": ent.text,
                        "etiqueta": ent.label_,
                        "start": ent.start_char,
                        "end": ent.end_char,
                        "prioridad": priority,
                        "origen": "spacy",
                    }
                )

        all_entities = detected_patterns + forced_words + valid_entities
        all_entities.sort(key=lambda item: (-item["start"], -(item.get("end", 0) - item.get("start", 0))))

        for ent in all_entities:
            overlaps = False
            for previous_start, previous_end in anonymized_spans:
                if not (ent["end"] <= previous_start or ent["start"] >= previous_end):
                    overlaps = True
                    break

            if overlaps:
                continue

            replacement = f"[{ent['etiqueta']}]"
            anonymized_text = anonymized_text[: ent["start"]] + replacement + anonymized_text[ent["end"] :]
            anonymized_spans.add((ent["start"], ent["end"]))

            entities_info.append(
                {
                    "texto_original": ent["texto"],
                    "tipo": ent["etiqueta"],
                    "posicion": ent["start"],
                    "prioridad": ent.get("prioridad"),
                    "origen": ent["origen"],
                }
            )

        return anonymized_text, entities_info

    def anonymize(self, text: str) -> str:
        anonymized_text, _ = self._anonymize_with_entities(text)
        return anonymized_text

    def process_text(self, text: str, ignore_words: set[str] | None = None) -> dict[str, Any]:
        anonymized_text, anonymized_entities = self._anonymize_with_entities(text, ignore_words=ignore_words)
        return {"texto_anon": anonymized_text, "ent_anon": anonymized_entities}
