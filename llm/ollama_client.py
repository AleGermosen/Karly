"""Ollama client — built but DORMANT until Phase 5.

On startup the router calls health_check(); if Ollama is unreachable it is
marked unavailable and everything routes to Gemini. This module never crashes
the bot when Ollama is down.
"""
from __future__ import annotations

import logging

import httpx

import config

logger = logging.getLogger(__name__)

# Flipped to True by health_check() when Ollama responds.
_available: bool = False


def is_available() -> bool:
    return _available


async def health_check(timeout: float = 2.0) -> bool:
    """Ping Ollama. Sets and returns availability. Never raises."""
    global _available
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(f"{config.OLLAMA_BASE_URL}/api/tags")
            resp.raise_for_status()
        _available = True
        logger.info("Ollama is available at %s", config.OLLAMA_BASE_URL)
    except Exception as exc:
        _available = False
        logger.info(
            "Ollama unavailable (%s) — routing everything to Gemini until "
            "Phase 5.",
            exc.__class__.__name__,
        )
    return _available


async def generate(
    prompt: str, *, system: str | None = None, timeout: float = 60.0
) -> str:
    """Generate via Ollama /api/generate. Raises on failure."""
    payload: dict = {
        "model": config.OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
    }
    if system:
        payload["system"] = system
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            f"{config.OLLAMA_BASE_URL}/api/generate", json=payload
        )
        resp.raise_for_status()
        data = resp.json()
    return data.get("response", "")
