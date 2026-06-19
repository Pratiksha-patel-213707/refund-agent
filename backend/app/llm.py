import json
import os
from functools import lru_cache
from typing import Any

from app.config import settings
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI


class LLMError(RuntimeError):
    """Raised when the configured LangChain LLM cannot return usable output."""


def _require_gemini_key() -> None:
    if not settings.is_api_key_configured:
        raise LLMError("Gemini API key is required for LLM requests.")


def _configure_google_env() -> None:
    _require_gemini_key()
    os.environ["GOOGLE_API_KEY"] = settings.GEMINI_API_KEY


@lru_cache(maxsize=2)
def _llm_model(model_name: str):
    _configure_google_env()
    return ChatGoogleGenerativeAI(
        model=model_name,
        google_api_key=settings.GEMINI_API_KEY,
        temperature=0,
        max_tokens=settings.GEMINI_MAX_OUTPUT_TOKENS,
        thinking_budget=settings.GEMINI_THINKING_BUDGET,
        max_retries=1,
        request_timeout=45,
        response_mime_type="application/json",
    )


@lru_cache(maxsize=2)
def _json_chain(model_name: str):
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", "{system_instruction}"),
            ("human", "{user_prompt}\n\nReturn valid JSON only."),
        ]
    )
    return prompt | _llm_model(model_name)


def _raise_langchain_error(exc: Exception) -> None:
    message = str(exc)
    lowered = message.lower()
    if "api key" in lowered or "permission_denied" in lowered or "unauthenticated" in lowered:
        raise LLMError(
            "Gemini API key is invalid, missing, or not allowed for this model. "
            "Paste a valid key into GEMINI_API_KEY in backend/.env and fully restart the backend."
        ) from exc
    if "quota" in lowered or "429" in message:
        raise LLMError(
            "Gemini quota was exceeded for the configured model. Check billing/quota or set GEMINI_MODEL to another available model."
        ) from exc
    raise LLMError(f"LangChain Gemini request failed: {message}") from exc


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
            else:
                parts.append(str(item))
        return "".join(parts)
    return str(content)


def _can_try_fallback(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(
        marker in message
        for marker in (
            "429",
            "quota",
            "resource_exhausted",
            "404",
            "not found",
            "503",
            "unavailable",
            "high demand",
        )
    )


def _langchain_generate(prompt: str) -> str:
    model_names = [settings.GEMINI_MODEL]
    if (
        settings.GEMINI_FALLBACK_MODEL
        and settings.GEMINI_FALLBACK_MODEL not in model_names
    ):
        model_names.append(settings.GEMINI_FALLBACK_MODEL)

    last_error: Exception | None = None
    for index, model_name in enumerate(model_names):
        try:
            message = _json_chain(model_name).invoke(
                {
                    "system_instruction": "You return valid JSON only. Do not include markdown or prose.",
                    "user_prompt": prompt,
                }
            )
            return _content_to_text(message.content)
        except Exception as exc:
            last_error = exc
            has_fallback = index < len(model_names) - 1
            if not has_fallback or not _can_try_fallback(exc):
                _raise_langchain_error(exc)

    assert last_error is not None
    _raise_langchain_error(last_error)


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].strip().lower() in {"```", "```json"}:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    candidates: list[dict[str, Any]] = []
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            parsed, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            candidates.append(parsed)

    if candidates:
        return candidates[-1]

    # Gemini can occasionally emit a complete sequence of object fields and
    # then append stray text immediately before the final closing brace. Parse
    # only fully valid top-level key/value pairs so one malformed suffix does
    # not discard otherwise usable structured output. This does not guess or
    # repair values: every retained key and value is decoded by json.JSONDecoder.
    recovered = _decode_object_prefix(text)
    if recovered:
        return recovered

    raise LLMError(f"LLM response did not contain valid JSON: {text[:500]}")


def _decode_object_prefix(text: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    start = text.find("{")
    if start < 0:
        return {}

    index = start + 1
    recovered: dict[str, Any] = {}
    length = len(text)

    def skip_whitespace(position: int) -> int:
        while position < length and text[position].isspace():
            position += 1
        return position

    while index < length:
        index = skip_whitespace(index)
        if index >= length or text[index] == "}":
            break
        if text[index] == ",":
            index = skip_whitespace(index + 1)

        try:
            key, key_end = decoder.raw_decode(text, index)
        except json.JSONDecodeError:
            break
        if not isinstance(key, str):
            break

        index = skip_whitespace(key_end)
        if index >= length or text[index] != ":":
            break
        index = skip_whitespace(index + 1)

        try:
            value, value_end = decoder.raw_decode(text, index)
        except json.JSONDecodeError:
            break

        recovered[key] = value
        index = skip_whitespace(value_end)
        if index >= length or text[index] == "}":
            break
        if text[index] != ",":
            # The next token is malformed trailing content. All fields stored
            # so far were independently valid and can be returned safely.
            break

    return recovered


def llm_json(prompt: str) -> dict[str, Any]:
    return _extract_json(_langchain_generate(prompt))
