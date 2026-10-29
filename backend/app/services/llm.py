import json
import logging
import re
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.core.config import get_settings
from app.schemas.interview import Evaluation, Question

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)
STRUCTURED_OUTPUT_ATTEMPTS = 3
MAX_DEBUG_RESPONSE_LENGTH = 2000


class LLMUnavailableError(RuntimeError):
    pass


class OllamaServiceError(LLMUnavailableError):
    pass


class OllamaService:
    def __init__(self) -> None:
        self.settings = get_settings()

    def generate(
        self,
        prompt: str,
        response_model: type[T] | None = None,
        *,
        allow_raw_response_logging: bool = False,
    ) -> str | T:
        if self.settings.mock_llm:
            return self._mock_response(prompt, response_model)
        url = f"{self.settings.ollama_base_url.rstrip('/')}/api/generate"
        payload: dict[str, object] = {
            "model": self.settings.ollama_model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.2},
        }
        if response_model is not None:
            payload["format"] = self._response_schema(response_model)

        last_error: Exception | None = None
        for attempt in range(STRUCTURED_OUTPUT_ATTEMPTS):
            try:
                response = httpx.post(url, json=payload, timeout=self.settings.ollama_timeout_seconds)
                response.raise_for_status()
                body = response.json()
                if not isinstance(body, dict):
                    raise ValueError("Ollama response must be a JSON object.")
                generated = body.get("response")
                if not isinstance(generated, str) or not generated.strip():
                    raise LLMUnavailableError("Ollama returned an empty response.")
                if response_model is None:
                    return generated
                try:
                    return response_model.model_validate(json.loads(self._extract_json(generated)))
                except (ValidationError, ValueError) as exc:
                    last_error = exc
                    self._log_invalid_structured_response(
                        generated,
                        response_model,
                        attempt + 1,
                        allow_raw_response_logging,
                        exc,
                    )
                    if attempt + 1 < STRUCTURED_OUTPUT_ATTEMPTS:
                        payload["prompt"] = (
                            f"{prompt}\n\nThe previous response was invalid. Return one complete JSON object "
                            "that exactly matches the required schema. Do not omit required fields or change "
                            "field types. Return JSON only."
                        )
                        logger.warning(
                            "Retrying Ollama structured output (%s/%s).",
                            attempt + 1,
                            STRUCTURED_OUTPUT_ATTEMPTS,
                        )
                        continue
                    raise LLMUnavailableError(
                        f"Ollama returned malformed JSON or output that does not match "
                        f"{response_model.__name__} after {STRUCTURED_OUTPUT_ATTEMPTS} attempts."
                    ) from exc
            except httpx.ConnectError as exc:
                last_error = exc
                if attempt + 1 < STRUCTURED_OUTPUT_ATTEMPTS:
                    logger.warning("Ollama connection failed on attempt %s/%s; retrying.", attempt + 1, STRUCTURED_OUTPUT_ATTEMPTS)
                    continue
                logger.exception("Ollama request failed")
                raise LLMUnavailableError(
                    f"Cannot connect to Ollama at {self.settings.ollama_base_url}. Start Ollama and retry."
                ) from exc
            except httpx.TimeoutException as exc:
                last_error = exc
                if attempt + 1 < STRUCTURED_OUTPUT_ATTEMPTS:
                    logger.warning("Ollama request timed out on attempt %s/%s; retrying.", attempt + 1, STRUCTURED_OUTPUT_ATTEMPTS)
                    continue
                logger.warning("Ollama request timed out after %s seconds", self.settings.ollama_timeout_seconds)
                raise LLMUnavailableError(
                    f"Ollama did not respond within {self.settings.ollama_timeout_seconds:g} seconds. "
                    "Try a smaller model or increase OLLAMA_TIMEOUT_SECONDS."
                ) from exc
            except httpx.HTTPStatusError as exc:
                detail = self._error_detail(exc.response)
                if exc.response.status_code == 404:
                    raise LLMUnavailableError(
                        f"Ollama model '{self.settings.ollama_model}' is not installed. "
                        f"Run: ollama pull {self.settings.ollama_model}"
                    ) from exc
                logger.warning("Ollama returned HTTP %s: %s", exc.response.status_code, detail)
                raise LLMUnavailableError(f"Ollama returned HTTP {exc.response.status_code}: {detail}") from exc
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt + 1 < STRUCTURED_OUTPUT_ATTEMPTS:
                    logger.warning("Ollama HTTP request failed on attempt %s/%s; retrying.", attempt + 1, STRUCTURED_OUTPUT_ATTEMPTS)
                    continue
                logger.exception("Ollama request failed")
                raise LLMUnavailableError(f"Ollama request failed: {exc}") from exc
            except ValueError as exc:
                last_error = exc
                if attempt + 1 < STRUCTURED_OUTPUT_ATTEMPTS:
                    logger.warning("Ollama returned an invalid response on attempt %s/%s; retrying.", attempt + 1, STRUCTURED_OUTPUT_ATTEMPTS)
                    continue
                logger.warning("Ollama returned an invalid response: %s", exc)
                raise LLMUnavailableError("Ollama returned an invalid response; check that the configured model is available.") from exc
        if last_error is not None:
            raise LLMUnavailableError("Ollama request failed after the configured retry limit.") from last_error
        raise LLMUnavailableError("Ollama request did not complete successfully.")

    @staticmethod
    def _response_schema(response_model: type[T]) -> dict[str, object]:
        schema = response_model.model_json_schema()
        if response_model is Evaluation:
            category_scores = schema["properties"]["category_scores"]
            required_categories = {
                name: {"type": "number", "minimum": 0, "maximum": 10}
                for name in (
                    "technical_correctness",
                    "relevance",
                    "depth",
                    "clarity",
                    "examples",
                )
            }
            category_scores["properties"] = required_categories
            category_scores["required"] = list(required_categories)
            category_scores["additionalProperties"] = {
                "type": "number",
                "minimum": 0,
                "maximum": 10,
            }
        return schema

    def _log_invalid_structured_response(
        self,
        generated: str,
        response_model: type[BaseModel],
        attempt: int,
        allow_raw_response_logging: bool,
        error: Exception,
    ) -> None:
        if self.settings.debug and allow_raw_response_logging:
            raw_response = generated[:MAX_DEBUG_RESPONSE_LENGTH]
            if len(generated) > MAX_DEBUG_RESPONSE_LENGTH:
                raw_response += "…[truncated]"
            logger.warning(
                "Invalid Ollama response for %s on attempt %s/%s; raw model response=%r; validation error=%s",
                response_model.__name__,
                attempt,
                STRUCTURED_OUTPUT_ATTEMPTS,
                raw_response,
                type(error).__name__,
            )
            return
        logger.warning(
            "Invalid Ollama response for %s on attempt %s/%s (validation error=%s); raw response omitted.",
            response_model.__name__,
            attempt,
            STRUCTURED_OUTPUT_ATTEMPTS,
            type(error).__name__,
        )

    def status(self) -> dict[str, object]:
        if self.settings.mock_llm:
            return {"mode": "mock", "available": True, "model": "deterministic-test-fixtures"}
        try:
            response = httpx.get(
                f"{self.settings.ollama_base_url.rstrip('/')}/api/tags",
                timeout=min(self.settings.ollama_timeout_seconds, 5),
            )
            response.raise_for_status()
            body = response.json()
            if not isinstance(body, dict):
                raise ValueError("Ollama tags response must be a JSON object.")
            models = [item.get("name", "") for item in body.get("models", []) if isinstance(item, dict)]
        except (httpx.HTTPError, ValueError) as exc:
            return {
                "mode": "ollama",
                "available": False,
                "model": self.settings.ollama_model,
                "message": f"Cannot reach Ollama at {self.settings.ollama_base_url}: {exc}",
            }
        installed = any(name == self.settings.ollama_model or name.startswith(f"{self.settings.ollama_model}:") for name in models)
        return {
            "mode": "ollama",
            "available": True,
            "model": self.settings.ollama_model,
            "model_installed": installed,
            "installed_models": models,
            "message": None if installed else f"Run: ollama pull {self.settings.ollama_model}",
        }

    @staticmethod
    def _error_detail(response: httpx.Response) -> str:
        try:
            body = response.json()
        except ValueError:
            return response.text[:500]
        return str(body.get("error", response.text))[:500] if isinstance(body, dict) else response.text[:500]

    @staticmethod
    def _mock_response(prompt: str, response_model: type[T] | None) -> str | T:
        if response_model is None:
            return "Mock LLM mode is enabled."
        if response_model.__name__ == "QuestionSet":
            requested = re.search(r"Create\s+(\d+)\s+personalized", prompt)
            count = int(requested.group(1)) if requested else 1
            mode = re.search(r"Interview type:\s*([a-zA-Z0-9_]+)", prompt)
            topic = mode.group(1).replace("_", " ").title() if mode else "General"
            questions = [
                Question(
                    text=f"[Mock] {topic}: Explain a key concept relevant to your selected interview type.",
                    topic=topic,
                    criteria=["Technical correctness", "Clarity", "Practical example"],
                    expected_concepts=["Accurate definition", "Reasoning", "Relevant example"],
                )
                for _ in range(count)
            ]
            return response_model.model_validate({"questions": [item.model_dump() for item in questions]})
        if response_model is Evaluation:
            return response_model.model_validate({
                "overall_score": 7,
                "category_scores": {
                    "technical_correctness": 7,
                    "relevance": 7,
                    "depth": 6,
                    "clarity": 8,
                    "examples": 6,
                },
                "strengths": ["Mock feedback: the answer addresses the question."],
                "missing_concepts": ["Add a concrete example to support the explanation."],
                "unsupported_statements": [],
                "improved_answer": "Mock sample only: answer directly, explain your reasoning, and add an accurate example.",
                "follow_up_question": "Can you describe a practical example?",
                "source_snippets": [],
            })
        raise LLMUnavailableError(f"Mock LLM has no fixture for {response_model.__name__}.")

    @staticmethod
    def _extract_json(text: str) -> str:
        cleaned = text.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned, flags=re.IGNORECASE)
        decoder = json.JSONDecoder()
        for index, character in enumerate(cleaned):
            if character not in "{[":
                continue
            try:
                _, end = decoder.raw_decode(cleaned, index)
                return cleaned[index:end]
            except json.JSONDecodeError:
                continue
        raise ValueError("No complete JSON object or array found.")
