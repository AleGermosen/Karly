"""Curriculum content validator.

Checks all YAML spine files and their matching JSONL banks for structural
errors before they reach the bot. Zero LLM calls — all checks are local.

Usage:
    python scripts/curriculum_lint.py          # check everything
    python scripts/curriculum_lint.py --rehash # also rewrite spine_hash fields
    python scripts/curriculum_lint.py curriculum/en/a1.yaml  # one file

Exit code 0 = all clear, 1 = errors found.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
CURRICULUM_DIR = ROOT / "curriculum"
BANK_DIR = ROOT / "curriculum" / "bank"

VALID_TYPES = {"mcq", "cloze", "transform", "produce"}
VALID_SKILLS = {"grammar", "vocabulary", "reading", "listening", "writing", "speaking"}
VALID_LEVELS = {"A1", "A2", "B1", "B1+", "B2", "C1"}
VALID_KINDS = {"grammar", "vocabulary", "reading", "listening"}


def _spine_hash(unit: dict) -> str:
    """Compute the spine hash for a unit dict."""
    payload = {
        "exercises": unit.get("exercises", []),
        "level": unit.get("level", ""),
        "skill": unit.get("skill", ""),
        "title_target": unit.get("title_target", ""),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return f"sha256:{digest}"


def lint_spine(path: Path, rehash: bool = False) -> list[str]:
    """Return a list of error strings for a spine YAML file."""
    try:
        import yaml  # type: ignore
    except ImportError:
        return [f"{path}: PyYAML not installed — run: pip install pyyaml"]

    try:
        with open(path) as f:
            units = yaml.safe_load(f)
    except Exception as exc:
        return [f"{path}: YAML parse error — {exc}"]

    if not isinstance(units, list):
        return [f"{path}: top-level must be a YAML list of units"]

    errors: list[str] = []
    seen_ids: set[str] = set()
    seen_orders: set[int] = set()

    for unit in units:
        uid = unit.get("id", "<missing id>")
        loc = f"{path}:{uid}"

        # Required fields
        for field in ("id", "kind", "level", "order", "title_target", "title_l1",
                      "can_do", "skill", "explain", "examples", "pitfalls", "exercises"):
            if field not in unit:
                errors.append(f"{loc}: missing required field '{field}'")

        if uid in seen_ids:
            errors.append(f"{loc}: duplicate id '{uid}'")
        seen_ids.add(uid)

        order = unit.get("order")
        if order is not None:
            if order in seen_orders:
                errors.append(f"{loc}: duplicate order {order}")
            seen_orders.add(order)

        level = unit.get("level", "")
        if level not in VALID_LEVELS:
            errors.append(f"{loc}: invalid level '{level}' (must be one of {sorted(VALID_LEVELS)})")

        skill = unit.get("skill", "")
        if skill not in VALID_SKILLS:
            errors.append(f"{loc}: invalid skill '{skill}' (must be one of {sorted(VALID_SKILLS)})")

        kind = unit.get("kind", "")
        if kind not in VALID_KINDS:
            errors.append(f"{loc}: invalid kind '{kind}'")

        # explain bullets — max 140 chars each
        for i, bullet in enumerate(unit.get("explain", []), 1):
            if len(bullet) > 140:
                errors.append(f"{loc}: explain[{i}] is {len(bullet)} chars (max 140)")

        # examples — exactly 3, each with target + gloss
        examples = unit.get("examples", [])
        if len(examples) != 3:
            errors.append(f"{loc}: need exactly 3 examples, got {len(examples)}")
        for i, ex in enumerate(examples, 1):
            for key in ("target", "gloss"):
                if key not in ex:
                    errors.append(f"{loc}: example[{i}] missing '{key}'")

        # exercises
        exercises = unit.get("exercises", [])
        if not exercises:
            errors.append(f"{loc}: no exercises defined")
        for ex in exercises:
            t = ex.get("type", "")
            if t not in VALID_TYPES:
                errors.append(f"{loc}: unknown exercise type '{t}'")
            if "n" not in ex:
                errors.append(f"{loc}: exercise type '{t}' missing 'n' count")

        # spine_hash
        expected_hash = _spine_hash(unit)
        stored_hash = unit.get("spine_hash", "")
        if stored_hash == "sha256:pending" or (rehash and stored_hash != expected_hash):
            unit["spine_hash"] = expected_hash
        elif stored_hash != expected_hash:
            errors.append(
                f"{loc}: spine_hash mismatch — stored '{stored_hash}', expected '{expected_hash}'. "
                "Run with --rehash to fix."
            )

    if rehash:
        try:
            import yaml  # type: ignore
            with open(path, "w") as f:
                yaml.dump(units, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
            print(f"  🔄 Rewrote hashes in {path}")
        except Exception as exc:
            errors.append(f"{path}: could not write rehashed file — {exc}")

    return errors


def lint_bank(bank_path: Path, spine_ids: set[str]) -> list[str]:
    """Return error strings for a JSONL bank file."""
    errors: list[str] = []
    seen_ids: set[str] = set()

    try:
        lines = bank_path.read_text().splitlines()
    except FileNotFoundError:
        errors.append(f"{bank_path}: bank file missing")
        return errors
    except Exception as exc:
        errors.append(f"{bank_path}: read error — {exc}")
        return errors

    unit_type_counts: dict[str, dict[str, int]] = {}

    for lineno, line in enumerate(lines, 1):
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"{bank_path}:{lineno}: JSON parse error — {exc}")
            continue

        item_id = item.get("id", f"<line {lineno}>")
        loc = f"{bank_path}:{lineno}:{item_id}"

        if item_id in seen_ids:
            errors.append(f"{loc}: duplicate question id")
        seen_ids.add(item_id)

        unit_id = item.get("unit", "")
        if spine_ids and unit_id not in spine_ids:
            errors.append(f"{loc}: references unknown unit '{unit_id}'")

        qtype = item.get("type", "")
        if qtype not in VALID_TYPES:
            errors.append(f"{loc}: unknown type '{qtype}'")

        # Accumulate counts per unit/type
        unit_type_counts.setdefault(unit_id, {}).setdefault(qtype, 0)
        unit_type_counts[unit_id][qtype] += 1

        # Type-specific field checks
        if qtype == "mcq":
            opts = item.get("options", [])
            if len(opts) != 4:
                errors.append(f"{loc}: mcq must have exactly 4 options, got {len(opts)}")
            answer = item.get("answer")
            if answer is None or not isinstance(answer, int) or answer not in range(4):
                errors.append(f"{loc}: mcq 'answer' must be an int 0-3")
            if "why" not in item:
                errors.append(f"{loc}: missing 'why' field")
            # Check that the wrong options are actually wrong (heuristic: prompt the reviewer)
            if "prompt" not in item:
                errors.append(f"{loc}: mcq missing 'prompt'")

        elif qtype == "cloze":
            for field in ("prompt", "answer", "accept", "why"):
                if field not in item:
                    errors.append(f"{loc}: cloze missing '{field}'")
            accept = item.get("accept", [])
            if not isinstance(accept, list) or not accept:
                errors.append(f"{loc}: cloze 'accept' must be a non-empty list")

        elif qtype == "transform":
            for field in ("prompt", "answer", "accept", "why"):
                if field not in item:
                    errors.append(f"{loc}: transform missing '{field}'")

        elif qtype == "produce":
            for field in ("prompt", "rubric", "model_answer"):
                if field not in item:
                    errors.append(f"{loc}: produce missing '{field}'")
            rubric = item.get("rubric", [])
            if not isinstance(rubric, list) or not rubric:
                errors.append(f"{loc}: produce 'rubric' must be a non-empty list")

    return errors


def find_spine_files(paths: list[Path]) -> list[Path]:
    """Return all spine YAML files under curriculum/ (excluding bank/)."""
    result = []
    for p in paths:
        if p.is_file() and p.suffix == ".yaml":
            result.append(p)
        elif p.is_dir():
            for spine in sorted(p.rglob("*.yaml")):
                if "bank" not in spine.parts:
                    result.append(spine)
    return result


def matching_bank(spine: Path) -> Path:
    """Given curriculum/en/a1.yaml, return curriculum/bank/en/a1.jsonl."""
    # spine is like curriculum/<lang>/<level>.yaml
    rel = spine.relative_to(CURRICULUM_DIR)  # en/a1.yaml
    return BANK_DIR / rel.with_suffix(".jsonl")


def main() -> int:
    parser = argparse.ArgumentParser(description="Karly curriculum content linter")
    parser.add_argument("paths", nargs="*", help="YAML files or directories to check (default: all)")
    parser.add_argument("--rehash", action="store_true", help="Rewrite spine_hash fields in place")
    args = parser.parse_args()

    input_paths = [Path(p) for p in args.paths] if args.paths else [CURRICULUM_DIR]
    spine_files = find_spine_files(input_paths)

    if not spine_files:
        print("No spine YAML files found.")
        return 0

    total_errors = 0
    for spine in spine_files:
        print(f"\nChecking {spine.relative_to(ROOT)} …")

        # Spine lint
        spine_errors = lint_spine(spine, rehash=args.rehash)
        for err in spine_errors:
            print(f"  ❌ {err}")
        total_errors += len(spine_errors)

        # Extract unit IDs for cross-reference
        try:
            import yaml  # type: ignore
            with open(spine) as f:
                units = yaml.safe_load(f) or []
            spine_ids = {u["id"] for u in units if "id" in u}
        except Exception:
            spine_ids = set()

        # Bank lint
        bank = matching_bank(spine)
        bank_errors = lint_bank(bank, spine_ids)
        for err in bank_errors:
            print(f"  ❌ {err}")
        total_errors += len(bank_errors)

        if not spine_errors and not bank_errors:
            print("  ✅ OK")

    print(f"\n{'✅ All clear.' if total_errors == 0 else f'❌ {total_errors} error(s) found.'}")
    return 0 if total_errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
