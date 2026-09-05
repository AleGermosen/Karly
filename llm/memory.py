"""Lightweight end-of-session memory summarizer.

Called every N user messages. Reads the recent conversation, extracts
personal facts (interests, job, goals) and a one-sentence topic summary,
then persists them on the User row so future sessions feel personalized.

The LLM call uses the cheapest available backend (Task.assess) and is
fire-and-forget — it must never block or crash the chat flow.
"""
from __future__ import annotations

import logging

from db import repo
from llm.router import Task
from llm.structured import generate_json

logger = logging.getLogger(__name__)

# How many recent user messages to feed into the summarizer.
_MSG_WINDOW = 20

_SYSTEM = """\
You are a memory assistant for a language-learning tutor bot. Your job is to \
read a sample of a student's recent messages and extract two things:

1. **facts** — a list of short, timeless personal facts about the student \
   (interests, hobbies, job, goals, hometown, family, travel plans, etc.). \
   Only include facts clearly stated or strongly implied. Skip learning-related \
   facts (grammar struggles, vocab) — those are tracked elsewhere. \
   Return at most 6 bullet points as plain strings.

2. **last_topic** — one concise sentence (≤15 words) describing what the \
   student mainly talked about in this sample.

Return ONLY a JSON object with keys "facts" (array of strings) and \
"last_topic" (string). No markdown, no commentary.
"""


async def run_session_summarizer(user_id: int, current_notes: str | None) -> None:
    """Extract facts from recent messages and persist them. Safe to call without await-guarding."""
    try:
        messages = repo.recent_user_messages(user_id, limit=_MSG_WINDOW)
        if len(messages) < 3:
            return

        conversation_sample = "\n".join(f"- {m}" for m in messages)
        existing = f"\nExisting known facts:\n{current_notes}" if current_notes else ""
        prompt = (
            f"Student messages (most recent first, reversed for brevity):\n"
            f"{conversation_sample}"
            f"{existing}\n\n"
            "Extract facts and last_topic as described."
        )

        parsed, _ = await generate_json(Task.assess, prompt, system=_SYSTEM)
        if not isinstance(parsed, dict):
            return

        new_facts: list[str] = parsed.get("facts") or []
        last_topic: str = parsed.get("last_topic") or ""

        # Merge new facts with existing ones, deduplicating by substring match.
        existing_facts: list[str] = []
        if current_notes:
            existing_facts = [
                line.lstrip("•- ").strip()
                for line in current_notes.splitlines()
                if line.strip()
            ]

        merged: list[str] = list(existing_facts)
        for fact in new_facts:
            fact = fact.strip()
            if not fact:
                continue
            # Skip if an existing fact already covers this (simple substring check).
            if not any(fact.lower() in e.lower() or e.lower() in fact.lower() for e in merged):
                merged.append(fact)

        # Cap at 20 facts to keep the prompt injection small.
        merged = merged[:20]
        notes_text = "\n".join(f"• {f}" for f in merged) if merged else None

        repo.update_user_memory(
            user_id,
            profile_notes=notes_text,
            last_session_summary=last_topic or None,
        )
        logger.debug("Memory updated for user %d: %d facts, topic=%r", user_id, len(merged), last_topic)

    except Exception:
        logger.exception("Session summarizer failed for user %d — ignoring", user_id)
