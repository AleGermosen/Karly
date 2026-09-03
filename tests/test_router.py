"""Router fallback-ladder tests with mocked backends. Run: python -m unittest -v."""
from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta, timezone

# Provide dummy env so `config` imports without a real .env.
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "dummy")
os.environ.setdefault("GEMINI_API_KEY", "dummy")

from llm import ollama_client, router  # noqa: E402
from llm.errors import (  # noqa: E402
    AllBackendsExhausted,
    BackendUnavailable,
    Generation,
    QuotaExceeded,
    RateLimited,
)
from llm.router import LadderState, RouteResult, RungState, Task, route  # noqa: E402


def _make_gen(text: str, model: str = "test-model") -> Generation:
    return Generation(text=text, model=model)


def _returns(text: str):
    async def _fn(prompt, **kw):
        return _make_gen(text)
    return _fn


def _quota(reset_at=None):
    async def _fn(prompt, **kw):
        raise RateLimited("429", reset_at=reset_at)
    return _fn


def _unavail():
    async def _fn(prompt, **kw):
        raise BackendUnavailable("down")
    return _fn


class RouterLadderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Patch out the backend shims to avoid real network calls
        self._orig_gemini = router._gemini_backend
        self._orig_ollama = router._ollama_backend
        self._orig_groq = router._groq_backend
        self._orig_state = router._ladder_state
        # Fresh state per test
        router._ladder_state = LadderState()

    def tearDown(self):
        router._gemini_backend = self._orig_gemini
        router._ollama_backend = self._orig_ollama
        router._groq_backend = self._orig_groq
        router._ladder_state = self._orig_state
        # Also restore rungs in _LADDERS to original functions
        self._rebuild_ladders()

    def _rebuild_ladders(self):
        """Rebuild _LADDERS using current router.*_backend references."""
        import config
        from llm.router import Rung, Task, _groq_backend, _gemini_backend, _ollama_backend
        groq_available = bool(config.GROQ_API_KEY)
        groq_70b = Rung(_groq_backend, config.GROQ_MODEL_PRIMARY, "⚡ Groq 70B")
        groq_8b = Rung(_groq_backend, config.GROQ_MODEL_FALLBACK, "⚡ Groq 8B")
        gem = Rung(_gemini_backend, config.GEMINI_MODEL, "🤖 Gemini")
        oll = Rung(_ollama_backend, config.OLLAMA_MODEL, "🐌 Ollama")
        if groq_available:
            heavy = [groq_70b, groq_8b, gem, oll]
            cheap = [groq_8b, gem, oll]
            analyze = [groq_70b, groq_8b, gem]
        else:
            heavy = [gem, oll]
            cheap = [gem, oll]
            analyze = [gem]
        for task in [Task.chat, Task.assess, Task.generate]:
            router._LADDERS[task] = heavy
        for task in [Task.lookup, Task.check]:
            router._LADDERS[task] = cheap
        router._LADDERS[Task.analyze] = analyze

    def _set_ladder(self, task: Task, rungs):
        router._LADDERS[task] = rungs

    def _rung(self, fn, label="test"):
        from llm.router import Rung
        return Rung(fn, "model-x", label)

    # ------------------------------------------------------------------
    # No-Groq ladder (GROQ_API_KEY unset — current production state)
    # ------------------------------------------------------------------

    async def test_chat_uses_gemini_when_groq_absent(self):
        rung_gem = self._rung(_returns("from-gemini"), "🤖 Gemini")
        rung_oll = self._rung(_unavail(), "🐌 Ollama")
        self._set_ladder(Task.chat, [rung_gem, rung_oll])
        self.assertEqual(await route(Task.chat, "Hallo"), "from-gemini")

    async def test_chat_falls_back_to_ollama_when_gemini_quota(self):
        rung_gem = self._rung(_quota(), "🤖 Gemini")
        rung_oll = self._rung(_returns("from-ollama"), "🐌 Ollama")
        self._set_ladder(Task.chat, [rung_gem, rung_oll])
        self.assertEqual(await route(Task.chat, "Hallo"), "from-ollama")

    async def test_all_exhausted_raises_quota_exceeded(self):
        rung_gem = self._rung(_quota(), "🤖 Gemini")
        rung_oll = self._rung(_quota(), "🐌 Ollama")
        self._set_ladder(Task.chat, [rung_gem, rung_oll])
        with self.assertRaises(QuotaExceeded):
            await route(Task.chat, "Hallo")

    # ------------------------------------------------------------------
    # Groq-first ladder (simulated by injecting Groq rungs manually)
    # ------------------------------------------------------------------

    async def test_ladder_order_groq_first(self):
        rung_groq = self._rung(_returns("from-groq"), "⚡ Groq 70B")
        rung_gem = self._rung(_returns("from-gemini"), "🤖 Gemini")
        self._set_ladder(Task.chat, [rung_groq, rung_gem])
        self.assertEqual(await route(Task.chat, "Hallo"), "from-groq")

    async def test_groq_ratelimited_falls_to_gemini(self):
        rung_groq = self._rung(_quota(), "⚡ Groq 70B")
        rung_gem = self._rung(_returns("from-gemini"), "🤖 Gemini")
        self._set_ladder(Task.chat, [rung_groq, rung_gem])
        self.assertEqual(await route(Task.chat, "Hallo"), "from-gemini")

    async def test_skip_on_cooldown(self):
        """A rung already marked daily-exhausted is skipped without a call."""
        calls = []

        async def groq_fn(prompt, **kw):
            calls.append("groq")
            return _make_gen("from-groq")

        async def gem_fn(prompt, **kw):
            calls.append("gem")
            return _make_gen("from-gemini")

        rung_groq = self._rung(groq_fn, "⚡ Groq 70B")
        rung_gem = self._rung(gem_fn, "🤖 Gemini")
        self._set_ladder(Task.chat, [rung_groq, rung_gem])

        # Pre-mark groq rung as daily-exhausted far in the future
        reset = datetime.now(timezone.utc) + timedelta(hours=12)
        await router._ladder_state.mark_daily(rung_groq, reset)

        result = await route(Task.chat, "Hallo")
        self.assertEqual(result, "from-gemini")
        self.assertNotIn("groq", calls)  # groq was skipped

    async def test_transient_cooldown_skips_rung(self):
        rung_gem = self._rung(_unavail(), "🤖 Gemini")
        rung_oll = self._rung(_returns("from-ollama"), "🐌 Ollama")
        self._set_ladder(Task.chat, [rung_gem, rung_oll])

        # First call marks Gemini transient-failed → falls to Ollama
        result = await route(Task.chat, "x")
        self.assertEqual(result, "from-ollama")

        # Second call: Gemini still on cooldown → skips to Ollama immediately
        calls = []

        async def gem_spy(prompt, **kw):
            calls.append("gem")
            return _make_gen("from-gemini")

        rung_gem2 = self._rung(gem_spy, "🤖 Gemini")
        router._LADDERS[Task.chat] = [rung_gem, rung_oll]  # rung_gem still on cooldown
        result2 = await route(Task.chat, "x")
        self.assertEqual(result2, "from-ollama")

    async def test_change_detection_via_route_result(self):
        """route_result returns the correct rung label each call."""
        rung_groq = self._rung(_returns("r1"), "⚡ Groq 70B")
        self._set_ladder(Task.chat, [rung_groq])
        result = await router.route_result(Task.chat, "x")
        self.assertEqual(result.rung.label, "⚡ Groq 70B")
        self.assertEqual(result.text, "r1")

    async def test_usage_passthrough(self):
        async def groq_with_tokens(prompt, **kw):
            return Generation(text="ok", model="llama", tokens_in=100, tokens_out=50)

        rung = self._rung(groq_with_tokens, "⚡ Groq 70B")
        self._set_ladder(Task.chat, [rung])
        result = await router.route_result(Task.chat, "x")
        self.assertEqual(result.tokens_in, 100)
        self.assertEqual(result.tokens_out, 50)

    async def test_json_output_flag_propagates(self):
        received = {}

        async def backend(prompt, **kw):
            received.update(kw)
            return _make_gen("{}}")

        rung = self._rung(backend, "test")
        self._set_ladder(Task.chat, [rung])
        await route(Task.chat, "x", json_output=True)
        self.assertTrue(received.get("json_output"))

    async def test_all_down_raises_quota_exceeded(self):
        rung1 = self._rung(_quota(), "A")
        rung2 = self._rung(_quota(), "B")
        self._set_ladder(Task.chat, [rung1, rung2])
        with self.assertRaises(QuotaExceeded):
            await route(Task.chat, "x")


if __name__ == "__main__":
    unittest.main()
