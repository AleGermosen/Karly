"""Tests for correction parsing — guards the ❌ → ✅ — reason line format that
vocab capture depends on. Run: python -m unittest -v."""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "dummy")
os.environ.setdefault("GEMINI_API_KEY", "dummy")

from bot.handlers.conversation import _parse_corrections  # noqa: E402


class ParseCorrectionsTests(unittest.TestCase):
    def test_single_correction(self):
        reply = "❌ Ich habe gegangen → ✅ Ich bin gegangen — motion verbs use sein"
        items = _parse_corrections(reply)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["term"], "Ich bin gegangen")
        self.assertEqual(items[0]["translation"], "motion verbs use sein")
        self.assertIn("→ ✅", items[0]["context_sentence"])

    def test_multiple_corrections_before_reply(self):
        reply = (
            "❌ der Auto → ✅ das Auto — Auto is neuter\n"
            "❌ Ich gehe zur Schule gestern → ✅ Ich bin gestern zur Schule gegangen "
            "— past tense + word order\n\n"
            "Sehr gut! Was hast du sonst gemacht?"
        )
        items = _parse_corrections(reply)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["term"], "das Auto")
        self.assertEqual(items[1]["term"], "Ich bin gestern zur Schule gegangen")

    def test_no_corrections(self):
        reply = "Perfekt! Erzähl mir mehr über deine Arbeit."
        self.assertEqual(_parse_corrections(reply), [])

    def test_double_dash_separator(self):
        reply = "❌ das Haus groß → ✅ das große Haus -- adjective ending"
        items = _parse_corrections(reply)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["translation"], "adjective ending")


if __name__ == "__main__":
    unittest.main()
