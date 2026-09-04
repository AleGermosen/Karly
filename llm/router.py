"""Fallback-ladder router.

Tries backends in priority order per task type; skips rungs that are on
cooldown (daily-exhausted or transiently failed); raises the original
QuotaExceeded / LLMUnavailable on total failure so handlers need no changes.

When GROQ_API_KEY is unset the Groq rungs are absent and the ladder collapses
to [Gemini, Ollama] — identical to the old behaviour.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Awaitable

import config
from llm import gemini, ollama_client
from llm.errors import (
    AllBackendsExhausted,
    BackendUnavailable,
    Generation,
    LLMUnavailable,
    QuotaExceeded,
    RateLimited,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Task taxonomy
# ---------------------------------------------------------------------------

class Task(str, Enum):
    chat = "chat"
    assess = "assess"
    analyze = "analyze"
    generate = "generate"
    lookup = "lookup"
    check = "check"


# ---------------------------------------------------------------------------
# Rung / state
# ---------------------------------------------------------------------------

BackendFn = Callable[..., Awaitable[Generation]]


@dataclass
class Rung:
    backend: BackendFn
    model_id: str
    label: str


@dataclass
class RungState:
    cooldown_until: datetime | None = None
    reason: str | None = None  # "daily" | "transient" | None

    def is_on_cooldown(self) -> bool:
        if self.cooldown_until is None:
            return False
        return datetime.now(timezone.utc) < self.cooldown_until


@dataclass
class RouteResult:
    text: str
    rung: Rung
    model: str
    tokens_in: int | None = None
    tokens_out: int | None = None


# ---------------------------------------------------------------------------
# Ladder state (in-process; swap backing store for Redis in Phase B)
# ---------------------------------------------------------------------------

class LadderState:
    def __init__(self) -> None:
        self._states: dict[str, RungState] = {}
        self._lock = asyncio.Lock()

    def _key(self, rung: Rung) -> str:
        return f"{rung.label}:{rung.model_id}"

    async def get(self, rung: Rung) -> RungState:
        async with self._lock:
            return self._states.get(self._key(rung), RungState())

    async def mark_daily(self, rung: Rung, reset_at: datetime | None) -> None:
        async with self._lock:
            self._states[self._key(rung)] = RungState(
                cooldown_until=reset_at, reason="daily"
            )

    async def mark_transient(self, rung: Rung, seconds: float = 60.0) -> None:
        from datetime import timedelta
        async with self._lock:
            until = datetime.now(timezone.utc) + timedelta(seconds=seconds)
            self._states[self._key(rung)] = RungState(
                cooldown_until=until, reason="transient"
            )

    def ladder_status(self, ladder: list[Rung]) -> list[dict]:
        now = datetime.now(timezone.utc)
        out = []
        for rung in ladder:
            state = self._states.get(self._key(rung), RungState())
            if state.is_on_cooldown():
                out.append({
                    "label": rung.label,
                    "state": "cooldown",
                    "available_at": state.cooldown_until,
                    "reason": state.reason,
                })
            else:
                out.append({"label": rung.label, "state": "ready"})
        return out


_ladder_state = LadderState()

# Concurrency semaphore — caps simultaneous LLM calls across the whole bot.
# Gemini's free tier allows ~10 req/min; keeping below that prevents 429s that
# would push every student down to Ollama at the same time.
_llm_semaphore = asyncio.Semaphore(config.LLM_CONCURRENCY_LIMIT)


# ---------------------------------------------------------------------------
# Backend shims — adapt existing clients to the unified signature
# ---------------------------------------------------------------------------

async def _gemini_backend(
    prompt: str,
    *,
    system: str | None = None,
    history: list[dict] | None = None,
    json_output: bool = False,
    model: str | None = None,
    max_tokens: int | None = None,
) -> Generation:
    try:
        text = await gemini.generate(
            prompt,
            system=system,
            history=history,
            json_output=json_output,
            max_output_tokens=max_tokens,
        )
        return Generation(text=text, model=config.GEMINI_MODEL)
    except QuotaExceeded:
        raise
    except LLMUnavailable:
        raise BackendUnavailable("Gemini unavailable")


async def _ollama_backend(
    prompt: str,
    *,
    system: str | None = None,
    history: list[dict] | None = None,
    json_output: bool = False,
    model: str | None = None,
    max_tokens: int | None = None,
) -> Generation:
    try:
        text = await ollama_client.generate(prompt, system=system)
        return Generation(text=text, model=config.OLLAMA_MODEL)
    except Exception as exc:
        raise BackendUnavailable(str(exc)) from exc


async def _groq_backend(
    prompt: str,
    *,
    system: str | None = None,
    history: list[dict] | None = None,
    json_output: bool = False,
    model: str | None = None,
    max_tokens: int | None = None,
) -> Generation:
    from llm import groq_client
    return await groq_client.generate(
        prompt,
        system=system,
        history=history,
        json_output=json_output,
        model=model,
        max_tokens=max_tokens,
    )


# ---------------------------------------------------------------------------
# Ladder definitions
# ---------------------------------------------------------------------------

def _build_ladders() -> dict[Task, list[Rung]]:
    groq_available = bool(config.GROQ_API_KEY)

    groq_70b = Rung(_groq_backend, config.GROQ_MODEL_PRIMARY, "⚡ Groq")
    groq_8b = Rung(_groq_backend, config.GROQ_MODEL_FALLBACK, "⚡ Groq Mini")
    gemini_rung = Rung(_gemini_backend, config.GEMINI_MODEL, "🤖 Gemini")
    ollama_rung = Rung(_ollama_backend, config.OLLAMA_MODEL, "🐌 Ollama")

    heavy = []
    cheap = []
    analyze = []
    # Structured tasks (assessment, doc analysis) need reliable JSON — the tiny
    # local Ollama model can't produce it, so it is left off these ladders.
    structured = []

    if groq_available:
        heavy = [groq_70b, groq_8b, gemini_rung, ollama_rung]
        cheap = [groq_8b, gemini_rung, ollama_rung]
        analyze = [groq_70b, groq_8b, gemini_rung]
        structured = [groq_70b, groq_8b, gemini_rung]
    else:
        heavy = [gemini_rung, ollama_rung]
        cheap = [gemini_rung, ollama_rung]
        analyze = [gemini_rung]
        structured = [gemini_rung]

    return {
        Task.chat: heavy,
        Task.assess: structured,
        Task.generate: heavy,
        Task.analyze: analyze,
        Task.lookup: cheap,
        Task.check: cheap,
    }


_LADDERS: dict[Task, list[Rung]] = _build_ladders()

# Per-task output token caps (T.3). Shorter caps reduce cost and keep replies
# conversational; structured tasks (assess/analyze) get more room for JSON.
_TASK_MAX_TOKENS: dict[Task, int] = {
    Task.chat: 700,
    Task.assess: 512,
    Task.generate: 1000,
    Task.analyze: 900,
    Task.lookup: 256,
    Task.check: 350,
}


# ---------------------------------------------------------------------------
# Core routing
# ---------------------------------------------------------------------------

async def route_result(
    task: Task,
    prompt: str,
    *,
    system: str | None = None,
    history: list[dict] | None = None,
    json_output: bool = False,
) -> RouteResult:
    """Walk the ladder for *task* and return the first successful RouteResult.

    Raises AllBackendsExhausted if every rung is on cooldown or fails.
    Raises LLMUnavailable if the concurrency queue times out.
    """
    # Concurrency gate — wait for a free slot, but don't hang forever.
    try:
        await asyncio.wait_for(
            _llm_semaphore.acquire(), timeout=config.LLM_QUEUE_TIMEOUT
        )
    except asyncio.TimeoutError:
        raise LLMUnavailable(
            "Server is busy right now — try again in a moment. 🙏"
        )

    try:
        effective_max_tokens = _TASK_MAX_TOKENS.get(task, 700)
        ladder = _LADDERS[task]
        for rung in ladder:
            state = await _ladder_state.get(rung)
            if state.is_on_cooldown():
                logger.debug(
                    "Skipping %s (cooldown until %s)", rung.label, state.cooldown_until
                )
                continue

            try:
                gen = await rung.backend(
                    prompt,
                    system=system,
                    history=history,
                    json_output=json_output,
                    model=rung.model_id,
                    max_tokens=effective_max_tokens,
                )
                return RouteResult(
                    text=gen.text,
                    rung=rung,
                    model=gen.model,
                    tokens_in=gen.tokens_in,
                    tokens_out=gen.tokens_out,
                )

            except (RateLimited, QuotaExceeded) as exc:
                reset_at = getattr(exc, "reset_at", None)
                logger.warning(
                    "%s quota/rate exhausted (reset=%s); moving down ladder.",
                    rung.label, reset_at,
                )
                await _ladder_state.mark_daily(rung, reset_at)

            except (BackendUnavailable, LLMUnavailable) as exc:
                logger.warning("%s transient failure: %s", rung.label, exc)
                await _ladder_state.mark_transient(rung, seconds=60.0)

            except Exception as exc:
                logger.warning("%s unexpected error: %s", rung.label, exc)
                await _ladder_state.mark_transient(rung, seconds=60.0)

        raise AllBackendsExhausted("All LLM backends exhausted or on cooldown")
    finally:
        _llm_semaphore.release()


async def route(
    task: Task,
    prompt: str,
    *,
    system: str | None = None,
    history: list[dict] | None = None,
    json_output: bool = False,
) -> str:
    """Convenience wrapper: returns plain text; raises QuotaExceeded or
    LLMUnavailable so existing handler except-clauses need no changes."""
    try:
        result = await route_result(
            task, prompt, system=system, history=history, json_output=json_output
        )
        return result.text
    except AllBackendsExhausted as exc:
        raise QuotaExceeded(str(exc)) from exc


# ---------------------------------------------------------------------------
# Status (for /status command, Phase A step 4)
# ---------------------------------------------------------------------------

def ladder_status(task: Task = Task.chat) -> list[dict]:
    """Return per-rung status for *task*. Reads cached state synchronously."""
    ladder = _LADDERS[task]
    now = datetime.now(timezone.utc)
    out = []
    for rung in ladder:
        state = _ladder_state._states.get(
            f"{rung.label}:{rung.model_id}", RungState()
        )
        if state.is_on_cooldown():
            out.append({
                "label": rung.label,
                "state": "cooldown",
                "available_at": state.cooldown_until,
                "reason": state.reason,
            })
        else:
            out.append({"label": rung.label, "state": "ready"})
    return out
