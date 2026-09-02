"""SM-2 scheduler tests. Run: python -m unittest tests.test_sm2 -v."""
from __future__ import annotations

import unittest
from datetime import datetime

from srs.sm2 import MIN_EASINESS, update

NOW = datetime(2026, 1, 1, 12, 0, 0)


class SM2Tests(unittest.TestCase):
    def test_first_correct_review_interval_1(self):
        s = update(2.5, 0, 0, quality=4, now=NOW)
        self.assertEqual(s.interval, 1)
        self.assertEqual(s.repetitions, 1)
        self.assertEqual(s.next_review_at, datetime(2026, 1, 2, 12, 0, 0))

    def test_second_correct_review_interval_6(self):
        s = update(2.5, 1, 1, quality=4, now=NOW)
        self.assertEqual(s.interval, 6)
        self.assertEqual(s.repetitions, 2)

    def test_third_review_scales_by_easiness(self):
        # Interval uses the easiness *before* this review's EF update (SM-2).
        s = update(2.5, 6, 2, quality=5, now=NOW)
        self.assertEqual(s.interval, round(6 * 2.5))
        self.assertEqual(s.repetitions, 3)

    def test_failure_resets_repetitions_and_interval(self):
        s = update(2.5, 20, 5, quality=1, now=NOW)
        self.assertEqual(s.repetitions, 0)
        self.assertEqual(s.interval, 1)
        self.assertEqual(s.next_review_at, datetime(2026, 1, 2, 12, 0, 0))

    def test_easiness_floor(self):
        ef = 1.3
        for _ in range(10):
            s = update(ef, 1, 1, quality=0, now=NOW)
            ef = s.easiness
        self.assertGreaterEqual(ef, MIN_EASINESS)

    def test_easy_grade_raises_easiness(self):
        s = update(2.5, 1, 1, quality=5, now=NOW)
        self.assertGreater(s.easiness, 2.5)


if __name__ == "__main__":
    unittest.main()
