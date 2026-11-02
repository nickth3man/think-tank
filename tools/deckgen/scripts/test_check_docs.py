#!/usr/bin/env python3
"""Tests for check_docs.py: each check must fail on a mutated input.

Run: .venv/bin/python tools/deckgen/scripts/test_check_docs.py
Exits 0 when every case behaves, 1 on the first regression. Stdlib only, no pytest.
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
CHECK = REPO / "tools/deckgen/scripts/check_docs.py"
SKILL = Path.home() / ".omp/agent/skills/deckgen-loop/SKILL.md"
PY = REPO / ".venv/bin/python"


def run(
    skill: Path | str = SKILL, repo: Path | str = REPO
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(PY), str(CHECK), "--repo", str(repo), "--skill", str(skill)],
        capture_output=True,
        text=True,
    )


def case(name: str, ok: bool, detail: str) -> bool:
    print(f"{'ok  ' if ok else 'FAIL'}  {name}")
    if not ok:
        print(f"      {detail}")
    return ok


def main() -> int:
    results: list[bool] = []

    clean = run()
    results.append(
        case(
            "clean tree passes",
            clean.returncode == 0 and clean.stdout.startswith("PASS"),
            clean.stdout + clean.stderr,
        )
    )

    with tempfile.TemporaryDirectory() as tmp:
        skill_copy = Path(tmp) / "SKILL.md"
        shutil.copy(SKILL, skill_copy)

        # 1. A restated proposition breaks single-sourcing.
        original = skill_copy.read_text()
        skill_copy.write_text(original + "\nThe title slide is well composed.\n")
        out = run(skill=skill_copy)
        results.append(
            case(
                "restated proposition fails",
                out.returncode == 1 and "restates a frozen proposition" in out.stdout,
                out.stdout,
            )
        )

        # 2. A lost step breaks the procedure.
        skill_copy.write_text(original.replace("## 6. Commit", "## 6b. Commit"))
        out = run(skill=skill_copy)
        results.append(
            case(
                "missing step fails",
                out.returncode == 1 and "expected steps 1-8" in out.stdout,
                out.stdout,
            )
        )

        # 3. A missing frontmatter flag fails.
        skill_copy.write_text(original.replace("disable-model-invocation: true", ""))
        out = run(skill=skill_copy)
        results.append(
            case(
                "missing invocation flag fails",
                out.returncode == 1 and "disable-model-invocation" in out.stdout,
                out.stdout,
            )
        )
        skill_copy.write_text(original)

    with tempfile.TemporaryDirectory() as tmp:
        # 4. A dangling referenced path fails (repo copy, instrument removed).
        repo_copy = Path(tmp) / "repo"
        shutil.copytree(REPO / "tools/deckgen", repo_copy / "tools/deckgen")
        shutil.copytree(REPO / "workflows", repo_copy / "workflows")
        (repo_copy / "tools/deckgen/GRADE.md").unlink()
        out = run(repo=repo_copy)
        results.append(
            case(
                "missing instrument fails",
                out.returncode == 1,
                out.stdout,
            )
        )

        # 5. A dropped stop condition fails.
        wf = repo_copy / "workflows/deckgen-iteration.md"
        wf.write_text(wf.read_text().replace("3. **Saturation**", "3. **Plateau**"))
        out = run(repo=repo_copy)
        results.append(
            case(
                "missing stop condition fails",
                out.returncode == 1 and "stop condition missing" in out.stdout,
                out.stdout,
            )
        )

        # 6. Disagreeing shared numbers fail.
        wf.write_text(
            wf.read_text()
            .replace("3. **Plateau**", "3. **Saturation**")
            .replace("0.85", "0.80")
        )
        out = run(repo=repo_copy)
        results.append(
            case(
                "disagreeing numbers fail",
                out.returncode == 1 and "does not state the exit bar" in out.stdout,
                out.stdout,
            )
        )

    failed = results.count(False)
    print(f"\n{len(results) - failed}/{len(results)} cases behave")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
