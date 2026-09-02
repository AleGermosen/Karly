"""Task router.

Routes by task type and handles quota fallback:
  chat, assess, analyze, generate -> Gemini
  lookup, check                    -> Ollama when available, else Gemini
On Gemini quota exhaustion the caller receives QuotaExceeded (unless Ollama is
available for lookup/check tasks, in which case we fall back to Ollama).
"""
from __future__ import annotations

import logging
from enum import Enum

from llm import gemini, ollama_client
from llm.gemini import LLMUnavailable, QuotaExceeded

logger = logging.getLogger(__name__)


class Task(str, Enum):
    chat = "chat"
    assess = "assess"
    analyze = "analyze"
    generate = "generate"
    lookup = "lookup"
    check = "check"


_OLLAMA_PREFERRED = {Task.lookup, Task.check}


async def route(
    task: Task,
    prompt: str,
    *,
    system: str | None = None,
    history: list[dict] | None = None,
    json_output: bool = False,
) -> str:
    """Dispatch a request to the right backend with fallback.

    Raises QuotaExceeded if Gemini is out of quota and no fallback is available.
    Raises LLMUnavailable if no backend can serve the request.
    """
    prefer_ollama = task in _OLLAMA_PREFERRED and ollama_client.is_available()

    if prefer_ollama:
        try:
            return await ollama_client.generate(prompt, system=system)
        except Exception as exc:
            logger.warning(
                "Ollama failed for %s (%s); falling back to Gemini.",
                task.value,
                exc,
            )

    # Gemini path (primary for chat/assess/analyze/generate, fallback for the
    # lookup/check tasks when Ollama is down).
    try:
        return await gemini.generate(
            prompt, system=system, history=history, json_output=json_output
        )
    except QuotaExceeded:
        # Last-ditch: if Ollama is available, use it even for Gemini tasks.
        if ollama_client.is_available():
            logger.warning(
                "Gemini quota exhausted; falling back to Ollama for %s.",
                task.value,
            )
            try:
                return await ollama_client.generate(prompt, system=system)
            except Exception as exc:
                raise LLMUnavailable(str(exc)) from exc
        raise
