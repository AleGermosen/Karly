"""Router fallback tests with mocked backends. Run: python -m unittest -v."""
from __future__ import annotations

import os
import unittest

# Provide dummy env so `config` imports without a real .env.
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "dummy")
os.environ.setdefault("GEMINI_API_KEY", "dummy")

from llm import ollama_client, router  # noqa: E402
from llm.gemini import QuotaExceeded  # noqa: E402
from llm.router import Task, route  # noqa: E402


class RouterFallbackTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.orig_gem = router.gemini.generate
        self.orig_oll_gen = ollama_client.generate
        self.orig_avail = ollama_client._available

    def tearDown(self):
        router.gemini.generate = self.orig_gem
        ollama_client.generate = self.orig_oll_gen
        ollama_client._available = self.orig_avail

    def _set_ollama(self, available: bool):
        ollama_client._available = available

    def _gemini_returns(self, text):
        async def fake(prompt, **kw):
            return text
        router.gemini.generate = fake

    def _gemini_quota(self):
        async def fake(prompt, **kw):
            raise QuotaExceeded("429")
        router.gemini.generate = fake

    def _ollama_returns(self, text):
        async def fake(prompt, **kw):
            return text
        ollama_client.generate = fake

    def _ollama_fails(self):
        async def fake(prompt, **kw):
            raise RuntimeError("ollama down")
        ollama_client.generate = fake

    async def test_lookup_uses_ollama_when_available(self):
        self._set_ollama(True)
        self._ollama_returns("from-ollama")
        self._gemini_returns("from-gemini")
        self.assertEqual(await route(Task.lookup, "das Haus"), "from-ollama")

    async def test_lookup_falls_back_to_gemini_when_ollama_down(self):
        self._set_ollama(False)
        self._gemini_returns("from-gemini")
        self.assertEqual(await route(Task.lookup, "das Haus"), "from-gemini")

    async def test_lookup_falls_back_to_gemini_when_ollama_errors(self):
        self._set_ollama(True)
        self._ollama_fails()
        self._gemini_returns("from-gemini")
        self.assertEqual(await route(Task.lookup, "das Haus"), "from-gemini")

    async def test_chat_uses_gemini(self):
        self._set_ollama(True)  # irrelevant for chat
        self._ollama_returns("from-ollama")
        self._gemini_returns("from-gemini")
        self.assertEqual(await route(Task.chat, "Hallo"), "from-gemini")

    async def test_chat_quota_falls_back_to_ollama_when_available(self):
        self._set_ollama(True)
        self._gemini_quota()
        self._ollama_returns("from-ollama")
        self.assertEqual(await route(Task.chat, "Hallo"), "from-ollama")

    async def test_chat_quota_raises_when_no_ollama(self):
        self._set_ollama(False)
        self._gemini_quota()
        with self.assertRaises(QuotaExceeded):
            await route(Task.chat, "Hallo")


if __name__ == "__main__":
    unittest.main()
