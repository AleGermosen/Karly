"""Shared TypedDicts for Karly's internal data structures (Phase 3)."""
from __future__ import annotations

from typing import Literal, TypedDict


class HistoryMessage(TypedDict):
    role: Literal["user", "assistant"]
    content: str


class CorrectionItem(TypedDict):
    term: str
    translation: str
    context_sentence: str
