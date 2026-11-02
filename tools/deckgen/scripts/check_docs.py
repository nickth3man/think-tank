#!/usr/bin/env python3
"""Check the deckgen loop documents agree with each other and with the repo.

The loop's prose makes invariants a machine can test: the frozen instrument lives in one
file, the other documents reference it instead of copying it, every path they name exists,
and the numbers two documents share are the same numbers. Prose drifts silently; this
script makes the drift fail.

Usage:
    check_docs.py [--repo PATH] [--skill PATH]

Exit 0 when every check passes, 1 on any failure (each printed with its file).
"""

import argparse
import re
import sys
from pathlib import Path

PROPOSITIONS = [
    "The slides use space well - empty areas look distributed and intentional",
    "Body text is consistent and appropriately sized for a presentation",
    "The layouts vary enough across slides to keep an executive engaged",
    "Images and charts are integrated cleanly and sized to fill their space",
    "The title slide is well composed.",
]

# Documents that must reference the instrument rather than restate it.
CONSUMERS = [
    "workflows/deckgen-iteration.md",
    "tools/deckgen/README.md",
    "tools/deckgen/SKILL.md",
]
INSTRUMENT = "tools/deckgen/GRADE.md"


def read(path: Path, failures: list[str]) -> str:
    if not path.is_file():
        failures.append(f"{path}: missing")
        return ""
    return path.read_text()


def check_instrument_owns_propositions(
    root: Path, skill: Path, failures: list[str]
) -> None:
    instrument = read(root / INSTRUMENT, failures)
    for p in PROPOSITIONS:
        if p not in instrument:
            failures.append(f"{INSTRUMENT}: proposition missing verbatim: {p[:44]}…")
    others = [root / c for c in CONSUMERS] + [skill]
    for path in others:
        if not path.is_file():
            continue
        body = path.read_text()
        for p in PROPOSITIONS:
            if p in body:
                failures.append(
                    f"{path}: restates a frozen proposition (single source of truth is {INSTRUMENT})"
                )


def check_referenced_paths(root: Path, skill: Path, failures: list[str]) -> None:
    """Every repo-relative path the documents name must exist."""
    docs = [
        skill,
        root / "workflows/deckgen-iteration.md",
        root / INSTRUMENT,
        root / "tools/deckgen/README.md",
        root / "tools/deckgen/SKILL.md",
    ]
    pattern = re.compile(r"`((?:tools|workflows|docs|ui)/[\w./-]+)`")
    for doc in docs:
        if not doc.is_file():
            continue
        for match in sorted(set(pattern.findall(doc.read_text()))):
            if not (root / match).exists():
                failures.append(
                    f"{doc.name}: references a path that does not exist: {match}"
                )


def check_shared_numbers(root: Path, skill: Path, failures: list[str]) -> None:
    """Numbers that appear in two documents must agree."""
    wf = read(root / "workflows/deckgen-iteration.md", failures)
    sk = read(skill, failures)
    shared = {
        "exit bar": (r"axes? ≥ (0\.\d+)", "0.85"),
        "noise floor": (r"±(0\.\d+)", "0.02"),
        "regression allowance": (r"more than (0\.\d+)", "0.05"),
    }
    for name, (pattern, expected) in shared.items():
        values = {v for doc in (wf, sk) for v in re.findall(pattern, doc)}
        for doc_name, doc in (("workflow", wf), ("skill", sk)):
            if expected not in doc:
                failures.append(f"{doc_name}: does not state the {name} ({expected})")
        if len(values) > 1:
            failures.append(f"{name}: documents disagree, found {sorted(values)}")


def check_skill_frontmatter(skill: Path, failures: list[str]) -> None:
    body = read(skill, failures)
    if not body.startswith("---"):
        failures.append(f"{skill}: missing YAML frontmatter")
        return
    head = body.split("---", 2)[1]
    name = re.search(r"^name:\s*(\S+)", head, re.M)
    if not name:
        failures.append(f"{skill}: frontmatter has no name")
    elif name.group(1) != skill.parent.name:
        failures.append(
            f"{skill}: name '{name.group(1)}' != directory '{skill.parent.name}'"
        )
    if "disable-model-invocation: true" not in head:
        failures.append(
            f"{skill}: expected disable-model-invocation: true (user-invoked skill)"
        )


def check_step_structure(skill: Path, failures: list[str]) -> None:
    """The procedure must keep its eight ordered steps; a lost step is a lost duty."""
    body = read(skill, failures)
    steps = re.findall(r"^## (\d+)\. (.+)$", body, re.M)
    numbers = [int(n) for n, _ in steps]
    if numbers != list(range(1, 9)):
        failures.append(f"{skill}: expected steps 1-8 in order, found {numbers}")
    for required in ("Baseline", "Grade", "Diagnose", "Verify", "Accept or reject",
                     "Commit", "Budget", "Finish"):
        if not any(required in title for _, title in steps):
            failures.append(f"{skill}: step '{required}' is missing")


def check_stop_conditions(root: Path, failures: list[str]) -> None:
    """The workflow must define every way a run is allowed to end."""
    wf = read(root / "workflows/deckgen-iteration.md", failures)
    for stop in ("exit bar", "budget", "Saturation", "No aimed fix left"):
        if stop.lower() not in wf.lower():
            failures.append(f"workflows/deckgen-iteration.md: stop condition missing: {stop}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".", help="repository root")
    ap.add_argument(
        "--skill",
        default=str(Path.home() / ".omp/agent/skills/deckgen-loop/SKILL.md"),
        help="the loop skill file",
    )
    args = ap.parse_args()
    root, skill = Path(args.repo).resolve(), Path(args.skill).expanduser()

    failures: list[str] = []
    check_skill_frontmatter(skill, failures)
    check_instrument_owns_propositions(root, skill, failures)
    check_referenced_paths(root, skill, failures)
    check_shared_numbers(root, skill, failures)
    check_step_structure(skill, failures)
    check_stop_conditions(root, failures)

    if failures:
        print(f"FAIL ({len(failures)} problems)")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(
        "PASS: instrument single-sourced, paths resolve, shared numbers agree, frontmatter valid"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
