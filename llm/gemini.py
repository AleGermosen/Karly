"""Gemini client: chat, assess, analyze, generate.

Wraps the async google-genai SDK with retry and quota-error handling. Raises
QuotaExceeded on 429/quota so callers can inform the user gracefully.
"""
from __future__ import annotations

import asyncio
import logging

from google import genai
from google.genai import errors, types

import config

logger = logging.getLogger(__name__)


class QuotaExceeded(Exception):
    """Gemini daily/rate quota hit (HTTP 429 / RESOURCE_EXHAUSTED)."""


class LLMUnavailable(Exception):
    """Gemini could not be reached or returned an unrecoverable error."""


# A single shared async client.
_client = genai.Client(api_key=config.GEMINI_API_KEY)


def _is_quota_error(exc: errors.APIError) -> bool:
    code = getattr(exc, "code", None)
    status = str(getattr(exc, "status", "")).upper()
    return code == 429 or "RESOURCE_EXHAUSTED" in status


async def generate(
    prompt: str,
    *,
    system: str | None = None,
    history: list[dict] | None = None,
    json_output: bool = False,
    max_retries: int = 2,
) -> str:
    """Generate a response.

    history: list of {"role": "user"|"assistant"|"model", "text": str}.
    Raises QuotaExceeded on quota errors, LLMUnavailable otherwise.
    """
    contents: list[types.Content] = []
    for msg in history or []:
        role = "model" if msg["role"] in ("assistant", "model") else "user"
        contents.append(
            types.Content(role=role, parts=[types.Part(text=msg["text"])])
        )
    contents.append(
        types.Content(role="user", parts=[types.Part(text=prompt)])
    )

    cfg_kwargs: dict = {}
    if system:
        cfg_kwargs["system_instruction"] = system
    if json_output:
        cfg_kwargs["response_mime_type"] = "application/json"
    gen_config = types.GenerateContentConfig(**cfg_kwargs) if cfg_kwargs else None

    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            resp = await _client.aio.models.generate_content(
                model=config.GEMINI_MODEL,
                contents=contents,
                config=gen_config,
            )
            text = resp.text
            if not text:
                raise LLMUnavailable("Empty response from Gemini")
            return text
        except errors.APIError as exc:
            last_exc = exc
            if _is_quota_error(exc):
                logger.warning("Gemini quota exceeded: %s", exc)
                raise QuotaExceeded(str(exc)) from exc
            logger.warning(
                "Gemini API error (attempt %d): %s", attempt + 1, exc
            )
        except Exception as exc:  # network, parsing, etc.
            last_exc = exc
            logger.warning("Gemini error (attempt %d): %s", attempt + 1, exc)
        if attempt < max_retries:
            await asyncio.sleep(1.5 * (attempt + 1))

    raise LLMUnavailable(str(last_exc) if last_exc else "unknown Gemini error")
