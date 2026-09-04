"""Smoke test — verify all major handlers import and their credit gates are wired.

Run with:  python -m scripts.smoke
No real LLM calls are made; the router is monkey-patched to return a fake result.
"""
from __future__ import annotations

import asyncio
import sys
import types
import unittest.mock as mock

# ---------------------------------------------------------------------------
# Patch LLM calls before any bot code is imported.
# ---------------------------------------------------------------------------

_FAKE_TEXT = "Smoke test reply."


class _FakeRung:
    label = "⚡ Groq"
    model_id = "fake"


class _FakeResult:
    text = _FAKE_TEXT
    rung = _FakeRung()
    model = "fake"
    tokens_in = 10
    tokens_out = 20


async def _fake_route(*a, **kw):
    return _FAKE_TEXT


async def _fake_route_result(*a, **kw):
    return _FakeResult()


async def _fake_generate_json(*a, **kw):
    return {"word": "Test", "part_of_speech": "noun", "definition": "Test word.", "example": "This is a test."}, "{}"


# Patch before import.
import importlib
import llm.router as _router_mod
_router_mod.route = _fake_route  # type: ignore
_router_mod.route_result = _fake_route_result  # type: ignore

import llm.structured as _struct_mod
_struct_mod.generate_json = _fake_generate_json  # type: ignore

# ---------------------------------------------------------------------------
# Now import everything to check for import errors.
# ---------------------------------------------------------------------------

CHECKS: list[tuple[str, str]] = []
ERRORS: list[str] = []


def check(label: str):
    def decorator(fn):
        CHECKS.append((label, fn))
        return fn
    return decorator


@check("Import bot.credits")
def _():
    import bot.credits  # noqa


@check("Import bot.handlers.conversation")
def _():
    import bot.handlers.conversation  # noqa


@check("Import bot.handlers.vocab")
def _():
    import bot.handlers.vocab  # noqa


@check("Import bot.handlers.media")
def _():
    import bot.handlers.media  # noqa


@check("Import bot.handlers.payments")
def _():
    import bot.handlers.payments  # noqa


@check("Import bot.handlers.classroom")
def _():
    import bot.handlers.classroom  # noqa


@check("Import bot.handlers.game")
def _():
    import bot.handlers.game  # noqa


@check("Import bot.main (full app build)")
def _():
    import bot.main  # noqa


@check("credits.COSTS has all expected keys")
def _():
    from bot.credits import COSTS
    expected = {"chat", "explain", "quiz", "daily", "daily_cached", "pdf", "learn", "summary"}
    missing = expected - COSTS.keys()
    assert not missing, f"Missing cost keys: {missing}"


@check("credits.credits_check returns ok for zero cost")
def _():
    from bot.credits import credits_check
    # user_id=0 doesn't exist; cost=0 always returns ok.
    assert credits_check(0, 0) == "ok"


@check("public_limit_check function is importable and callable")
def _():
    from bot.credits import public_limit_check, session_reset_minutes, metered
    assert callable(public_limit_check)
    assert callable(session_reset_minutes)
    assert callable(metered)


@check("VocabSource.personal exists")
def _():
    from db.models import VocabSource
    assert VocabSource.personal == "personal"


@check("bot.types TypedDicts importable")
def _():
    from bot.types import HistoryMessage, CorrectionItem  # noqa


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main() -> int:
    passed = 0
    failed = 0
    for label, fn in CHECKS:
        try:
            fn()
            print(f"  ✅ {label}")
            passed += 1
        except Exception as exc:
            print(f"  ❌ {label}: {exc}")
            failed += 1

    print(f"\n{passed} passed, {failed} failed.")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
