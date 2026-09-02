"""Helpers for requesting and defensively parsing JSON from the LLM."""
from __future__ import annotations

import json
import logging

from llm.router import Task, route

logger = logging.getLogger(__name__)


def extract_json(text: str) -> dict | list | None:
    """Best-effort parse of a JSON object/array from model output."""
    if not text:
        return None
    s = text.strip()
    # Strip ```json fences if present.
    if s.startswith("```"):
        s = s.strip("`")
        if s.lower().startswith("json"):
            s = s[4:]
        s = s.strip()
    try:
        return json.loads(s)
    except ValueError:
        pass
    # Fall back to the outermost {...} or [...] span.
    for open_c, close_c in (("{", "}"), ("[", "]")):
        start = s.find(open_c)
        end = s.rfind(close_c)
        if start != -1 and end > start:
            try:
                return json.loads(s[start : end + 1])
            except ValueError:
                continue
    return None


async def generate_json(
    task: Task,
    prompt: str,
    *,
    system: str | None = None,
    history: list[dict] | None = None,
) -> tuple[dict | list | None, str]:
    """Request JSON, retry once on parse failure. Returns (parsed_or_None, raw)."""
    raw = await route(
        task, prompt, system=system, history=history, json_output=True
    )
    parsed = extract_json(raw)
    if parsed is not None:
        return parsed, raw

    logger.warning("JSON parse failed; retrying once.")
    retry_prompt = (
        prompt
        + "\n\nYour previous answer was not valid JSON. Reply with ONLY the "
        "JSON object, no markdown, no commentary."
    )
    raw2 = await route(
        task, retry_prompt, system=system, history=history, json_output=True
    )
    return extract_json(raw2), raw2
