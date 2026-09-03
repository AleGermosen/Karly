"""Bayesian Knowledge Tracing (BKT) per-skill mastery estimator.

BKT models a hidden binary state: mastered vs. not-mastered.
After each observed answer, mastery probability is updated via Bayes,
then bumped by the learning-transition probability.

Standard parameters from the educational data mining literature:
  P_L0 = 0.10  initial probability of mastery
  P_T  = 0.10  transition: P(mastered on this try | not yet mastered)
  P_G  = 0.20  guess:  P(correct | not mastered)
  P_S  = 0.10  slip:   P(incorrect | mastered)

Skills tracked: grammar, reading, comprehension, production, functional, vocab
"""
from __future__ import annotations

P_L0 = 0.10
P_T  = 0.10
P_G  = 0.20
P_S  = 0.10

MASTERY_THRESHOLD = 0.95

SKILLS = ("grammar", "reading", "comprehension", "production", "functional", "vocab")


def init_state() -> dict[str, float]:
    """Return a fresh BKT state dict for all tracked skills."""
    return {s: P_L0 for s in SKILLS}


def update(p_mastered: float, correct: bool) -> float:
    """Update mastery probability given one observation.

    Returns the new P(mastered) after the learning-transition step.
    """
    p_correct = p_mastered * (1 - P_S) + (1 - p_mastered) * P_G

    if 0 < p_correct < 1:
        if correct:
            p_L = (p_mastered * (1 - P_S)) / p_correct
        else:
            p_L = (p_mastered * P_S) / (1 - p_correct)
    else:
        p_L = p_mastered

    # Learning transition: chance of mastering after this opportunity
    p_L_next = p_L + (1 - p_L) * P_T
    return min(1.0, max(0.0, p_L_next))


def mastery_bar(p: float) -> str:
    """Short Unicode progress bar for display in Telegram messages."""
    filled = round(p * 10)
    return "█" * filled + "░" * (10 - filled) + f" {round(p * 100)}%"


def mastered(p: float) -> bool:
    return p >= MASTERY_THRESHOLD
