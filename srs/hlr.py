"""Half-Life Regression (HLR) spaced-repetition scheduler.

Duolingo-style HLR: instead of SM-2's fixed multiplier, the half-life h (days)
tracks how long until recall probability drops to 50%.

  p(recall | t) = 2^(-t / h)

After each review, h is updated based on the "surprise"
(actual outcome minus predicted probability):

  delta   = correct - p_predicted
  h_new   = h * 2^(ALPHA * delta)
  clamped to [MIN_HALF_LIFE, MAX_HALF_LIFE] days.

Next review is scheduled when p_recall == TARGET_RECALL:
  t_next  = h * log(TARGET_RECALL) / log(0.5)   [days]
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta

ALPHA = 0.3             # learning-rate multiplier
MIN_HALF_LIFE = 0.5     # ½ day minimum (12 hours)
MAX_HALF_LIFE = 365.0   # one year maximum
TARGET_RECALL = 0.9     # schedule reviews at this recall probability
INIT_HALF_LIFE = 1.0    # starting value for new items


def recall_probability(elapsed_days: float, half_life: float) -> float:
    """P(recall) after elapsed_days given half_life."""
    if half_life <= 0:
        return 0.0
    return 2.0 ** (-elapsed_days / half_life)


def update(half_life: float, elapsed_days: float, correct: bool) -> float:
    """Apply one review and return the updated half-life (days)."""
    p_predicted = recall_probability(elapsed_days, half_life)
    delta = (1.0 if correct else 0.0) - p_predicted
    new_h = half_life * (2.0 ** (ALPHA * delta))
    return max(MIN_HALF_LIFE, min(MAX_HALF_LIFE, new_h))


def days_until_next(half_life: float) -> int:
    """Days until the next review, targeting TARGET_RECALL recall."""
    t = half_life * math.log(TARGET_RECALL) / math.log(0.5)
    return max(1, round(t))


def next_review_at(half_life: float, now: datetime | None = None) -> datetime:
    now = now or datetime.utcnow()
    return now + timedelta(days=days_until_next(half_life))
