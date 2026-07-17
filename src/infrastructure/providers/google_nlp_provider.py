"""Google NLP provider that builds the extraction prompt, calls the API and normalizes the response."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from time import perf_counter, sleep
from typing import Any

import httpx

from src.domain.exceptions.domain_exceptions import ProviderError, ProviderTimeoutError
from src.domain.interfaces.nlp_provider import NLPProviderInterface
from src.config.settings import Settings


@dataclass(slots=True)
class GoogleNLPProvider(NLPProviderInterface):
    settings: Settings

    def extract_labels(self, anonymized_text: str, prompt_version: str, allowed_labels: list[str], timeout_seconds: int = 10) -> dict[str, Any]:
        if not self.settings.google_nlp_endpoint:
            raise ProviderError("Google NLP endpoint is not configured")
        if not self.settings.google_api_key:
            raise ProviderError("Google API key is not configured")

        payload = self._build_payload(anonymized_text=anonymized_text, allowed_labels=allowed_labels)
        started_at = perf_counter()
        last_error: Exception | None = None
        max_retries = max(0, int(self.settings.google_nlp_max_retries))
        total_attempts = max_retries + 1

        for attempt in range(total_attempts):
            remaining_timeout = timeout_seconds - (perf_counter() - started_at)
            if remaining_timeout <= 0:
                raise ProviderTimeoutError("Google NLP timeout exceeded")

            try:
                with httpx.Client(timeout=remaining_timeout) as client:
                    response = client.post(
                        self.settings.google_nlp_endpoint,
                        headers={
                            "Content-Type": "application/json",
                            "x-goog-api-key": self.settings.google_api_key,
                        },
                        json=payload,
                    )
            except httpx.TimeoutException as exc:
                last_error = exc
                if attempt >= max_retries:
                    raise ProviderTimeoutError("Google NLP timeout exceeded") from exc
                self._sleep_with_backoff(attempt=attempt)
                continue
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt >= max_retries:
                    raise ProviderError(f"Google NLP connection error: {exc}") from exc
                self._sleep_with_backoff(attempt=attempt)
                continue

            if response.status_code in (429,) or 500 <= response.status_code < 600:
                if attempt < max_retries:
                    self._sleep_with_backoff(attempt=attempt, retry_after=response.headers.get("Retry-After"))
                    continue
                transient_details = self._extract_google_error_message(response)
                raise ProviderError(f"Google NLP transient failure: {response.status_code}. {transient_details}")

            if 400 <= response.status_code < 500:
                client_details = self._extract_google_error_message(response)
                raise ProviderError(f"Google NLP client error: {response.status_code}. {client_details}")

            try:
                data = response.json()
            except ValueError as exc:
                raise ProviderError("Google NLP returned non-JSON response") from exc

            hallazgos = self._extract_labels(data)
            return {
                "hallazgos": hallazgos,
                "model": self.settings.google_nlp_model,
                "provider": "google",
                "raw_response": data,
                "prompt_version": prompt_version,
            }

        if isinstance(last_error, httpx.TimeoutException):
            raise ProviderTimeoutError("Google NLP timeout exceeded") from last_error
        raise ProviderError(f"Google NLP call failed: {last_error}")

    def _sleep_with_backoff(self, attempt: int, retry_after: str | None = None) -> None:
        backoff_seconds = min(
            self.settings.google_nlp_max_backoff_seconds,
            self.settings.google_nlp_base_backoff_seconds * (2 ** attempt),
        )

        retry_after_seconds = self._parse_retry_after_seconds(retry_after)
        if retry_after_seconds is not None:
            backoff_seconds = min(self.settings.google_nlp_max_backoff_seconds, retry_after_seconds)

        if backoff_seconds > 0:
            sleep(backoff_seconds)

    def _parse_retry_after_seconds(self, retry_after: str | None) -> float | None:
        if not retry_after:
            return None
        try:
            seconds = float(retry_after)
        except ValueError:
            return None
        if seconds < 0:
            return None
        return seconds

    def _extract_google_error_message(self, response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            text = response.text.strip()
            return text[:300] if text else "No details returned by provider"

        error_block = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error_block, dict):
            message = str(error_block.get("message", "")).strip()
            status = str(error_block.get("status", "")).strip()
            details = [part for part in [status, message] if part]
            if details:
                return " - ".join(details)

        return "No details returned by provider"

    def health_check(self, timeout_seconds: int = 2) -> bool:
        if not self.settings.google_nlp_endpoint:
            return False

        try:
            with httpx.Client(timeout=timeout_seconds) as client:
                response = client.options(self.settings.google_nlp_endpoint)
                return response.status_code < 500
        except httpx.HTTPError:
            return False

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
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.1,
                "responseMimeType": "application/json",
            },
        }

    def _extract_labels(self, response_json: dict[str, Any]) -> list[dict[str, Any]]:
        if "hallazgos" in response_json and isinstance(response_json.get("hallazgos"), list):
            return self._normalize_hallazgos(response_json["hallazgos"])

        if "labels" in response_json and isinstance(response_json.get("labels"), list):
            # Compatibilidad hacia atras con la forma de respuesta del proveedor anterior.
            return self._normalize_legacy_labels(response_json["labels"])

        candidate_text = self._extract_candidate_text(response_json)
        if not candidate_text:
            return []

        candidate_text = self._strip_markdown_code_fences(candidate_text)
        parsed = self._try_parse_json(candidate_text)
        if isinstance(parsed, dict) and isinstance(parsed.get("hallazgos"), list):
            return self._normalize_hallazgos(parsed["hallazgos"])

        if isinstance(parsed, dict) and isinstance(parsed.get("labels"), list):
            return self._normalize_legacy_labels(parsed["labels"])
        return []

    def _extract_candidate_text(self, response_json: dict[str, Any]) -> str:
        candidates = response_json.get("candidates", [])
        if not candidates:
            return ""
        content = candidates[0].get("content", {})
        parts = content.get("parts", [])
        if not parts:
            return ""
        return str(parts[0].get("text", ""))

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
            normalized.append({"etiqueta": name, "descripcion": ""})
        return normalized
