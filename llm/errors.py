"""Unified LLM exception taxonomy and result type.

All backends raise these; router.py catches and re-raises them.
QuotaExceeded / LLMUnavailable are kept as the primary names so existing
`except` clauses in handlers continue to work unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class Generation:
    text: str
    model: str
    tokens_in: int | None = None
    tokens_out: int | None = None


class QuotaExceeded(Exception):
    """Rate / daily quota hit for a backend.

    reset_at: when the limit clears (may be None if unknown).
    scope: "requests" | "tokens" | None.
    """

    def __init__(
        self,
        msg: str = "",
        *,
        reset_at: datetime | None = None,
        scope: str | None = None,
    ) -> None:
        super().__init__(msg)
        self.reset_at = reset_at
        self.scope = scope


class LLMUnavailable(Exception):
    """Transient backend failure, network error, or misconfiguration."""


class AllBackendsExhausted(Exception):
    """Every rung in the fallback ladder is on cooldown or failed."""


# Design-doc aliases — use either name in new code.
RateLimited = QuotaExceeded
BackendUnavailable = LLMUnavailable
