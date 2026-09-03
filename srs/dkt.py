"""Deep Knowledge Tracing (DKT) — LSTM-based recall probability prediction.

Predicts, for each vocab item, the probability that AJ will recall it correctly
on the next review, given his full review history as a time sequence.

Architecture: small LSTM (hidden=32), input=(item_idx_norm, correct_bit),
output=sigmoid per item (n_items). Trained entirely in-process on the user's
review history each time it's called.

Gated: only active when
  1. numpy + tensorflow are importable, AND
  2. The user has at least MIN_REVIEWS logged review entries.

All callers receive None when the gate is not met; they should fall back to
HLR or SM-2 scheduling transparently.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

MIN_REVIEWS = 50
HIDDEN_SIZE = 32
EPOCHS = 10
LEARNING_RATE = 0.001

_TF_AVAILABLE: bool | None = None  # lazily checked


def _check_tf() -> bool:
    global _TF_AVAILABLE
    if _TF_AVAILABLE is None:
        try:
            import numpy  # noqa: F401
            import tensorflow  # noqa: F401
            _TF_AVAILABLE = True
        except ImportError:
            _TF_AVAILABLE = False
            logger.info("DKT disabled: tensorflow/numpy not installed.")
    return _TF_AVAILABLE


def train(
    reviews: list[dict],
    n_items: int,
) -> object | None:
    """Train a DKT model on the user's review history.

    Args:
        reviews:  List of {item_idx (int, 0-based), correct (bool)} dicts,
                  ordered oldest-first.
        n_items:  Number of distinct vocab items (vocabulary size).

    Returns:
        Trained keras Model, or None if gating conditions are not met.
    """
    if not _check_tf() or len(reviews) < MIN_REVIEWS or n_items < 2:
        return None

    import numpy as np
    import tensorflow as tf

    norm = max(n_items, 1)
    seq = np.array(
        [[r["item_idx"] / norm, 1.0 if r["correct"] else 0.0] for r in reviews],
        dtype=np.float32,
    )
    targets = np.zeros((len(reviews), n_items), dtype=np.float32)
    for i, r in enumerate(reviews):
        targets[i, r["item_idx"]] = 1.0 if r["correct"] else 0.0

    # Single-user: one long sequence — shape (1, T, features)
    X = seq[np.newaxis, :, :]
    Y = targets[np.newaxis, :, :]

    model = tf.keras.Sequential([
        tf.keras.layers.Input(shape=(None, 2)),
        tf.keras.layers.LSTM(HIDDEN_SIZE, return_sequences=True),
        tf.keras.layers.Dense(n_items, activation="sigmoid"),
    ])
    model.compile(
        optimizer=tf.keras.optimizers.Adam(LEARNING_RATE),
        loss="binary_crossentropy",
    )
    model.fit(X, Y, epochs=EPOCHS, verbose=0)
    logger.info("DKT trained on %d reviews, %d items.", len(reviews), n_items)
    return model


def predict_recall(
    model: object,
    reviews: list[dict],
    n_items: int,
    item_idx_map: dict[int, int],
) -> dict[int, float]:
    """Predict recall probability per vocab_id given history.

    Args:
        model:        Keras model from train().
        reviews:      Same list format as train().
        n_items:      Vocabulary size.
        item_idx_map: {vocab_id -> item_idx} mapping.

    Returns:
        {vocab_id: p_recall} for every id in item_idx_map, or {} on failure.
    """
    if model is None or not reviews or not _check_tf():
        return {}

    import numpy as np

    norm = max(n_items, 1)
    seq = np.array(
        [[r["item_idx"] / norm, 1.0 if r["correct"] else 0.0] for r in reviews],
        dtype=np.float32,
    )[np.newaxis, :, :]  # (1, T, 2)

    preds = model.predict(seq, verbose=0)[0, -1, :]  # last timestep, all items
    return {vid: float(preds[idx]) for vid, idx in item_idx_map.items()
            if 0 <= idx < len(preds)}
