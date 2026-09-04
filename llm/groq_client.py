"""Groq backend — OpenAI-compatible chat completions via httpx.

Returns Generation; raises RateLimited (= QuotaExceeded) or
BackendUnavailable (= LLMUnavailable). Never raises anything else.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import httpx

import config
from llm.errors import BackendUnavailable, Generation, RateLimited

logger = logging.getLogger(__name__)

_BASE = config.GROQ_BASE_URL.rstrip("/")
_COMPLETIONS = f"{_BASE}/chat/completions"

# Latest quota snapshot per model, updated on every successful response.
# {model_id: {remaining_req, limit_req, remaining_tok, limit_tok, reset_at}}
# In-process only — resets on restart, repopulates on the next call.
_quota: dict[str, dict] = {}


def quota_snapshot() -> dict[str, dict]:
    """Return the most recent rate-limit snapshot for each Groq model seen."""
    return dict(_quota)


def _parse_reset(header_val: str | None) -> datetime | None:
    """Parse a Groq reset header (float seconds from now) into an absolute UTC datetime."""
    if not header_val:
        return None
    try:
        seconds = float(header_val)
        return datetime.now(timezone.utc) + timedelta(seconds=seconds)
    except (ValueError, TypeError):
        return None


async def generate(
    prompt: str,
    *,
    system: str | None = None,
    history: list[dict] | None = None,
    json_output: bool = False,
    model: str | None = None,
    max_tokens: int | None = None,
) -> Generation:
    """Call Groq chat completions and return a Generation.

    model: overrides config.GROQ_MODEL_PRIMARY when supplied (for the 8B rung).
    Raises RateLimited or BackendUnavailable; never raises anything else.
    """
    if not config.GROQ_API_KEY:
        raise BackendUnavailable("GROQ_API_KEY not set")

    resolved_model = model or config.GROQ_MODEL_PRIMARY

    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    for msg in history or []:
        role = "assistant" if msg["role"] in ("assistant", "model") else "user"
        messages.append({"role": role, "content": msg["text"]})
    messages.append({"role": "user", "content": prompt})

    payload: dict = {
        "model": resolved_model,
        "messages": messages,
        "temperature": config.GROQ_TEMPERATURE,
        "max_tokens": max_tokens or config.GROQ_MAX_TOKENS,
        "stream": False,
    }
    if json_output:
        payload["response_format"] = {"type": "json_object"}

    headers = {
        "Authorization": f"Bearer {config.GROQ_API_KEY}",
        "Content-Type": "application/json",
    }

    timeout = httpx.Timeout(
        connect=config.GROQ_CONNECT_TIMEOUT,
        read=config.GROQ_READ_TIMEOUT,
        write=10.0,
        pool=5.0,
    )

    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(_COMPLETIONS, json=payload, headers=headers)

            if resp.status_code == 429:
                retry_after = resp.headers.get("retry-after")
                reset_requests = resp.headers.get("x-ratelimit-reset-requests")
                reset_at = _parse_reset(retry_after or reset_requests)
                scope = "tokens" if "token" in resp.text.lower() else "requests"
                raise RateLimited(
                    f"Groq 429 on {resolved_model}",
                    reset_at=reset_at,
                    scope=scope,
                )

            if resp.status_code in (401, 403):
                logger.error(
                    "Groq auth error %s — check GROQ_API_KEY", resp.status_code
                )
                raise BackendUnavailable(f"Groq auth error {resp.status_code}")

            resp.raise_for_status()

            data = resp.json()
            text = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                or ""
            )
            if not text:
                raise BackendUnavailable("Empty content from Groq")

            usage = data.get("usage", {})
            tokens_in = usage.get("prompt_tokens")
            tokens_out = usage.get("completion_tokens")

            # Capture rate-limit headers for /status display and proactive
            # exhaustion detection.
            h = resp.headers
            rem_req = h.get("x-ratelimit-remaining-requests")
            lim_req = h.get("x-ratelimit-limit-requests")
            rem_tok = h.get("x-ratelimit-remaining-tokens")
            lim_tok = h.get("x-ratelimit-limit-tokens")
            reset_hdr = h.get("x-ratelimit-reset-requests")
            _quota[resolved_model] = {
                "remaining_req": int(rem_req) if rem_req is not None else None,
                "limit_req": int(lim_req) if lim_req is not None else None,
                "remaining_tok": int(rem_tok) if rem_tok is not None else None,
                "limit_tok": int(lim_tok) if lim_tok is not None else None,
                "reset_at": _parse_reset(reset_hdr),
            }

            if rem_req is not None:
                try:
                    if int(rem_req) == 0:
                        raise RateLimited(
                            f"Groq {resolved_model} requests exhausted",
                            reset_at=_parse_reset(reset_hdr),
                            scope="requests",
                        )
                except ValueError:
                    pass

            return Generation(
                text=text,
                model=resolved_model,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
            )

        except RateLimited:
            raise  # propagate immediately — no retry
        except BackendUnavailable:
            raise
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            last_exc = exc
            logger.warning("Groq network error (attempt %d): %s", attempt + 1, exc)
        except httpx.HTTPStatusError as exc:
            last_exc = exc
            logger.warning("Groq HTTP error (attempt %d): %s", attempt + 1, exc)
        except Exception as exc:
            last_exc = exc
            logger.warning("Groq unexpected error (attempt %d): %s", attempt + 1, exc)

        if attempt < 2:
            await asyncio.sleep(1.5 * (attempt + 1))

    raise BackendUnavailable(
        f"Groq unavailable after retries: {last_exc}"
    )
