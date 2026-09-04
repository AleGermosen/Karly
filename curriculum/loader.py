"""Curriculum loader — reads spine YAML and bank JSONL files at import time.

All data lives in memory after the first import; files are never re-read during
a session. If a bank file is missing, the unit's question list is empty and the
bot falls back to LLM-generated questions (existing behaviour).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml  # type: ignore

_ROOT = Path(__file__).parent  # curriculum/
_BANK = _ROOT / "bank"


@dataclass
class Unit:
    id: str
    kind: str
    level: str
    order: int
    title_target: str
    title_l1: str
    can_do: str
    prereqs: list[str]
    skill: str
    explain: list[str]
    examples: list[dict[str, str]]
    pitfalls: list[str]
    exercises: list[dict[str, Any]]
    spine_hash: str
    # Populated by the loader from the matching .jsonl bank.
    questions: list[dict[str, Any]] = field(default_factory=list)

    @property
    def lang(self) -> str:
        """Language code extracted from the unit id, e.g. 'en' from 'en.a1.g01'."""
        return self.id.split(".")[0]

    def questions_of_type(self, qtype: str) -> list[dict[str, Any]]:
        return [q for q in self.questions if q.get("type") == qtype]


# { lang: { level: [Unit, …] } }  — sorted by Unit.order
_catalogue: dict[str, dict[str, list[Unit]]] = {}


def _load_spine(path: Path) -> list[Unit]:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    units = []
    for u in raw or []:
        units.append(Unit(
            id=u["id"],
            kind=u.get("kind", "grammar"),
            level=u["level"],
            order=u["order"],
            title_target=u["title_target"],
            title_l1=u["title_l1"],
            can_do=u["can_do"],
            prereqs=u.get("prereqs", []),
            skill=u["skill"],
            explain=u.get("explain", []),
            examples=u.get("examples", []),
            pitfalls=u.get("pitfalls", []),
            exercises=u.get("exercises", []),
            spine_hash=u.get("spine_hash", ""),
        ))
    return sorted(units, key=lambda u: u.order)


def _load_bank(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    questions = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    questions.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return questions


def _build_catalogue() -> None:
    for lang_dir in sorted(_ROOT.iterdir()):
        if not lang_dir.is_dir() or lang_dir.name == "bank":
            continue
        lang = lang_dir.name  # "en" | "de"
        _catalogue[lang] = {}
        for spine_path in sorted(lang_dir.glob("*.yaml")):
            level_key = spine_path.stem.upper()  # "a1" → "A1"
            units = _load_spine(spine_path)

            bank_path = _BANK / lang / spine_path.with_suffix(".jsonl").name
            bank_items = _load_bank(bank_path)
            bank_by_unit: dict[str, list[dict]] = {}
            for item in bank_items:
                uid = item.get("unit", "")
                bank_by_unit.setdefault(uid, []).append(item)

            for unit in units:
                unit.questions = bank_by_unit.get(unit.id, [])

            _catalogue[lang][level_key] = units


_build_catalogue()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_unit(unit_id: str) -> Unit | None:
    """Look up a unit by its full id (e.g. 'en.a1.g01')."""
    parts = unit_id.split(".")
    if len(parts) < 3:
        return None
    lang, level = parts[0], parts[1].upper()
    for unit in _catalogue.get(lang, {}).get(level, []):
        if unit.id == unit_id:
            return unit
    return None


def list_units(lang: str, level: str) -> list[Unit]:
    """All units for a lang/level, sorted by order."""
    return list(_catalogue.get(lang, {}).get(level.upper(), []))


def next_unit(lang: str, level: str, after_order: int) -> Unit | None:
    """Return the first unit with order > after_order, or None."""
    for unit in list_units(lang, level):
        if unit.order > after_order:
            return unit
    return None


def first_unpassed_unit(
    lang: str,
    level: str,
    passed_ids: set[str],
) -> Unit | None:
    """Return the first unit the student hasn't passed yet."""
    for unit in list_units(lang, level):
        if unit.id not in passed_ids:
            return unit
    return None


def available_langs() -> list[str]:
    return sorted(_catalogue.keys())


def available_levels(lang: str) -> list[str]:
    return sorted(_catalogue.get(lang, {}).keys())
