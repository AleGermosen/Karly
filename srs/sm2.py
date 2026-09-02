"""SM-2 spaced-repetition scheduler.

Pure functions over the SRS fields stored on VocabItem:
  sm2_easiness (float, >= 1.3), sm2_interval (days), sm2_repetitions (int).

Quality grade q is 0-5:
  0-2 = incorrect / forgotten  -> reset repetitions, review again tomorrow
  3-5 = correct                -> advance the interval
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

MIN_EASINESS = 1.3


@dataclass
class SM2State:
    easiness: float
    interval: int
    repetitions: int
    next_review_at: datetime


def update(
    easiness: float,
    interval: int,
    repetitions: int,
    quality: int,
    now: datetime | None = None,
) -> SM2State:
    """Apply one SM-2 review and return the new state."""
    now = now or datetime.utcnow()
    quality = max(0, min(5, int(quality)))

    if quality < 3:
        repetitions = 0
        interval = 1
    else:
        if repetitions == 0:
            interval = 1
        elif repetitions == 1:
            interval = 6
        else:
            interval = round(interval * easiness)
        repetitions += 1

    # Easiness factor update (always applied).
    easiness = easiness + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    if easiness < MIN_EASINESS:
        easiness = MIN_EASINESS

    next_review_at = now + timedelta(days=interval)
    return SM2State(easiness, interval, repetitions, next_review_at)
