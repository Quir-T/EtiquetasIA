"""Qwen NLP provider backed by an Ollama HTTP endpoint."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from time import perf_counter
from typing import Any

import httpx

from src.config.settings import Settings
from src.domain.exceptions.domain_exceptions import ProviderError, ProviderTimeoutError
from src.domain.interfaces.nlp_provider import NLPProviderInterface


@dataclass(slots=True)
class QwenNLPProvider(NLPProviderInterface):
    settings: Settings

    def extract_labels(self, anonymized_text: str, prompt_version: str, allowed_labels: list[str], timeout_seconds: int = 10) -> dict[str, Any]:
        if not self.settings.qwen_nlp_endpoint:
            raise ProviderError("Qwen NLP endpoint is not configured")
        if not self.settings.qwen_nlp_model:
            raise ProviderError("Qwen NLP model is not configured")

        payload = self._build_payload(anonymized_text=anonymized_text, allowed_labels=allowed_labels)
        started_at = perf_counter()

        try:
            with httpx.Client(timeout=timeout_seconds) as client:
                response = client.post(
                    self.settings.qwen_nlp_endpoint,
                    headers=self._build_headers(),
                    json=payload,
                )
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError("Qwen NLP timeout exceeded") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"Qwen NLP connection error: {exc}") from exc

        if response.status_code >= 400:
            raise ProviderError(f"Qwen NLP error: {response.status_code}. {self._extract_error_message(response)}")

        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderError("Qwen NLP returned non-JSON response") from exc

        hallazgos = self._extract_labels(data)
        return {
            "hallazgos": hallazgos,
            "model": self.settings.qwen_nlp_model,
            "provider": "qwen",
            "raw_response": data,
            "prompt_version": prompt_version,
            "processing_ms": int((perf_counter() - started_at) * 1000),
        }

    def health_check(self, timeout_seconds: int = 2) -> bool:
        if not self.settings.qwen_nlp_endpoint:
            return False

        base_url = self._base_url()
        try:
            with httpx.Client(timeout=timeout_seconds) as client:
                response = client.get(f"{base_url}/api/tags")
                return response.status_code < 500
        except httpx.HTTPError:
            return False

    def _build_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.settings.qwen_api_key:
            headers["Authorization"] = f"Bearer {self.settings.qwen_api_key}"
        return headers

    def _base_url(self) -> str:
        endpoint = self.settings.qwen_nlp_endpoint.rstrip("/")
        if endpoint.endswith("/api/generate"):
            return endpoint[: -len("/api/generate")]
        return endpoint

    def _extract_error_message(self, response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            text = response.text.strip()
            return text[:300] if text else "No details returned by provider"

        if isinstance(payload, dict):
            for key in ("error", "message"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()

        return "No details returned by provider"

    def _build_payload(self, anonymized_text: str, allowed_labels: list[str]) -> dict[str, Any]:
        allowed_block = "\n".join(allowed_labels)
        prompt = (
            "# PROMPT: Extraccion estructurada de antecedentes clinicos desde anamnesis\n\n"
            "## ROL\n"
            "Eres un sistema de extraccion de informacion clinica especializado en anamnesis en espanol. "
            "Tu unica funcion es leer el texto medico provisto e identificar que informacion del paciente coincide con "
            "un conjunto cerrado y predefinido de etiquetas clinicas. No diagnosticas, no interpretas mas alla de lo escrito, "
            "no completas informacion faltante.\n\n"
            "## ETIQUETAS VALIDAS (lista cerrada - usar EXACTAMENTE este texto, sin alterar mayusculas, tildes ni redaccion)\n\n"
            f"{allowed_block}\n\n"
            "IMPORTANTE: ningun valor del campo etiqueta puede ser distinto a uno de los textos de arriba, copiado de forma literal y exacta. "
            "Esta lista es cerrada: no se crean, infieren ni adaptan etiquetas nuevas bajo ningun concepto.\n\n"
            "## TAREA\n"
            "1. Lee el texto de anamnesis completo.\n"
            "2. Identifica fragmentos que correspondan a informacion real y explicita del paciente "
            "(antecedentes, habitos, diagnosticos, alergias, consultas) que coincidan semanticamente con alguna etiqueta de la lista.\n"
            "3. Para cada coincidencia encontrada, generar un objeto con:\n"
            "   - etiqueta: el texto EXACTO de la lista cerrada que mejor corresponde.\n"
            "   - descripcion: una parafrasis breve, clinica y normalizada del hallazgo (NO copiar literal el texto fuente; resumir en 3-12 palabras).\n"
            "4. Si NO hay ninguna coincidencia en todo el texto, devolver hallazgos vacio.\n\n"
            "## FORMATO DE SALIDA (obligatorio, sin excepciones)\n"
            "Responder UNICAMENTE con un JSON valido, sin texto adicional antes o despues, sin markdown, con esta estructura exacta:\n"
            '{"hallazgos":[{"etiqueta":"TABAQUISMO","descripcion":"tabaquismo activo, 10 cig/dia, 20 anos de evolucion"}]}\n\n'
            "## REGLAS DE DESAMBIGUACION\n"
            "- DIABETES TIPO 1 vs DIABETES TIPO 2: solo asignar si el tipo esta explicito o se infiere sin ambiguedad.\n"
            "- TABAQUISMO vs EX TABAQUISTA: EX TABAQUISTA solo si hay cese explicito.\n"
            "- EPOC vs ASMA: no asignar una por otra.\n"
            "- TRASTORNOS CARDIACOS vs ARRITMIA vs INSUFICIENCIA CARDIACA: usar especifica cuando aplique.\n"
            "- TRASTORNO NEUROLOGICO vs EPILEPSIA/MIGRANA/ACV PREVIO: preferir etiqueta especifica.\n"
            "- Grupos sanguineos: extraer solo si se menciona explicitamente grupo y factor.\n"
            "- PREGUNTA O DUDA: usar solo ante consulta explicita.\n"
            "- EMBARAZO y PATOLOGIAS DEL SISTEMA REPRODUCTOR FEMENINO: usar solo si esta explicito.\n"
            "- OBESIDAD/SEDENTARISMO/EJERCICIO FISICO: requieren mencion explicita.\n\n"
            "## REGLAS GENERALES ANTI-ALUCINACION\n"
            "1. No inventar informacion.\n"
            "2. No asignar etiquetas por especulacion, antecedentes familiares ni negaciones.\n"
            "3. Ante la duda entre dos etiquetas, omitir antes que adivinar.\n"
            "4. Nunca generar una etiqueta fuera de la lista cerrada.\n"
            "5. Una misma etiqueta puede repetirse si hay hallazgos distintos.\n"
            "6. No alterar el texto de la etiqueta.\n"
            "7. El JSON de salida debe ser valido y parseable.\n"
            "8. Si el texto esta vacio, es ilegible o no contiene anamnesis real: devolver {\"hallazgos\": []}.\n\n"
            "Responde solo con el JSON correspondiente.\n\n"
            f"TEXTO:\n{anonymized_text}"
        )

        return {
            "model": self.settings.qwen_nlp_model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0.1,
            },
        }

    def _extract_labels(self, response_json: dict[str, Any]) -> list[dict[str, Any]]:
        if "hallazgos" in response_json and isinstance(response_json.get("hallazgos"), list):
            return self._normalize_hallazgos(response_json["hallazgos"])

        for candidate_text in self._candidate_texts(response_json):
            cleaned_text = self._strip_model_wrappers(candidate_text)
            if not cleaned_text:
                continue

            parsed = self._try_parse_json(cleaned_text)
            if parsed is None:
                parsed = self._try_parse_json_object_fragment(cleaned_text)

            if isinstance(parsed, dict) and isinstance(parsed.get("hallazgos"), list):
                return self._normalize_hallazgos(parsed["hallazgos"])

            if isinstance(parsed, dict) and isinstance(parsed.get("labels"), list):
                return self._normalize_legacy_labels(parsed["labels"])

            if isinstance(parsed, dict) and isinstance(parsed.get("tags"), list):
                return self._normalize_tags(parsed["tags"])

        # Fallback de ultimo recurso para salidas donde el modelo devuelve una estructura de tags tipo JSON
        # envuelta en texto adicional que no puede parsearse como un unico objeto JSON.
        for candidate_text in self._candidate_texts(response_json):
            normalized_from_tags = self._normalize_tags_from_text(candidate_text)
            if normalized_from_tags:
                return normalized_from_tags

        return []

    def _candidate_texts(self, response_json: dict[str, Any]) -> list[str]:
        candidates: list[str] = []
        for key in ("response", "thinking"):
            value = response_json.get(key)
            if isinstance(value, str) and value.strip():
                candidates.append(value.strip())

        message_block = response_json.get("message")
        if isinstance(message_block, dict):
            content = message_block.get("content")
            if isinstance(content, str) and content.strip():
                candidates.append(content.strip())

        return candidates

    def _strip_model_wrappers(self, text: str) -> str:
        text = self._strip_markdown_code_fences(text)
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
        return text.strip()

    def _strip_markdown_code_fences(self, text: str) -> str:
        match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return text.strip()

    def _try_parse_json(self, text: str) -> dict[str, Any] | None:
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return None
        if isinstance(parsed, dict):
            return parsed
        return None

    def _try_parse_json_object_fragment(self, text: str) -> dict[str, Any] | None:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return None
        return self._try_parse_json(text[start : end + 1])

    def _normalize_hallazgos(self, hallazgos: list[Any]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for hallazgo in hallazgos:
            if not isinstance(hallazgo, dict):
                continue
            etiqueta = str(hallazgo.get("etiqueta", "")).strip()
            descripcion = str(hallazgo.get("descripcion", "")).strip()
            if not etiqueta or not descripcion:
                continue
            normalized.append({"etiqueta": etiqueta, "descripcion": descripcion})
        return normalized

    def _normalize_legacy_labels(self, labels: list[Any]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for label in labels:
            if not isinstance(label, dict):
                continue
            name = str(label.get("name", "")).strip()
            if not name:
                continue
            normalized.append({"etiqueta": name, "descripcion": name})
        return normalized

    def _normalize_tags(self, tags: list[Any]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for tag in tags:
            if not isinstance(tag, dict):
                continue
            etiqueta = str(tag.get("etiqueta") or tag.get("tag") or "").strip()
            descripcion = str(tag.get("descripcion") or tag.get("description") or "").strip()
            if not etiqueta or not descripcion:
                continue
            normalized.append({"etiqueta": etiqueta, "descripcion": descripcion})
        return normalized

    def _normalize_tags_from_text(self, text: str) -> list[dict[str, Any]]:
        cleaned_text = self._strip_model_wrappers(text)
        if not cleaned_text:
            return []
        tags_matches = re.findall(r'\{\s*"tag"\s*:\s*"(.*?)"\s*,\s*"description"\s*:\s*"(.*?)"\s*\}', cleaned_text, flags=re.DOTALL)
        normalized: list[dict[str, Any]] = []
        for tag, description in tags_matches:
            etiqueta = str(tag).strip()
            descripcion = str(description).strip()
            if not etiqueta or not descripcion:
                continue
            normalized.append({"etiqueta": etiqueta, "descripcion": descripcion})
        return normalized