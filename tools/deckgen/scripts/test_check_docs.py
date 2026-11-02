#!/usr/bin/env python3
"""Tests for check_docs.py: each check must fail on a mutated input.

Standard library only, so it runs with no extra dependency:
    .venv/bin/python -m unittest tools.deckgen.scripts.test_check_docs -v
and as a plain script (which exits 1 on any failure):
    .venv/bin/python tools/deckgen/scripts/test_check_docs.py
"""

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
CHECK = REPO / "tools/deckgen/scripts/check_docs.py"
# The versioned copy, not the machine-local install: a fresh clone must be able to run these.
SKILL = REPO / "workflows/deckgen-loop/SKILL.md"
# The interpreter running this suite, so a fresh clone without .venv still works.
PY = Path(sys.executable)


def run(
    skill: Path | str = SKILL, repo: Path | str = REPO
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(PY), str(CHECK), "--repo", str(repo), "--skill", str(skill)],
        capture_output=True,
        text=True,
    )


class CheckDocsTest(unittest.TestCase):
    def test_clean_tree_passes(self):
        out = run()
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertTrue(out.stdout.startswith("PASS"), out.stdout)

    def test_restated_proposition_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill_copy = Path(tmp) / "SKILL.md"
            shutil.copy(SKILL, skill_copy)
            skill_copy.write_text(
                skill_copy.read_text() + "\nThe title slide is well composed.\n"
            )
            out = run(skill=skill_copy)
            self.assertEqual(out.returncode, 1, out.stdout)
            self.assertIn("restates a frozen proposition", out.stdout)

    def test_missing_step_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill_copy = Path(tmp) / "SKILL.md"
            original = SKILL.read_text()
            skill_copy.write_text(original.replace("## 6. Commit", "## 6b. Commit"))
            out = run(skill=skill_copy)
            self.assertEqual(out.returncode, 1, out.stdout)
            self.assertIn("expected steps 1-8", out.stdout)

    def test_missing_invocation_flag_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill_copy = Path(tmp) / "SKILL.md"
            original = SKILL.read_text()
            skill_copy.write_text(
                original.replace("disable-model-invocation: true", "")
            )
            out = run(skill=skill_copy)
            self.assertEqual(out.returncode, 1, out.stdout)
            self.assertIn("disable-model-invocation", out.stdout)

    def _repo_copy(self, tmp: str) -> Path:
        repo_copy = Path(tmp) / "repo"
        shutil.copytree(REPO / "tools/deckgen", repo_copy / "tools/deckgen")
        shutil.copytree(REPO / "workflows", repo_copy / "workflows")
        shutil.copytree(REPO / "docs", repo_copy / "docs")
        shutil.copytree(REPO / "ui/deckgen", repo_copy / "ui/deckgen")
        return repo_copy

    def test_missing_instrument_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_copy = self._repo_copy(tmp)
            (repo_copy / "tools/deckgen/GRADE.md").unlink()
            out = run(repo=repo_copy)
            self.assertEqual(out.returncode, 1, out.stdout)

    def test_missing_stop_condition_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_copy = self._repo_copy(tmp)
            wf = repo_copy / "workflows/deckgen-iteration.md"
            wf.write_text(wf.read_text().replace("3. **Saturation**", "3. **Plateau**"))
            out = run(repo=repo_copy)
            self.assertEqual(out.returncode, 1, out.stdout)
            self.assertIn("stop condition missing", out.stdout)

    def test_default_skill_is_inside_the_repo(self):
        """The suite must not depend on a machine-local install."""
        out = subprocess.run(
            [str(PY), str(CHECK)], cwd=str(REPO), capture_output=True, text=True
        )
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertTrue((REPO / "workflows/deckgen-loop/SKILL.md").is_file())

    def test_disagreeing_numbers_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_copy = self._repo_copy(tmp)
            wf = repo_copy / "workflows/deckgen-iteration.md"
            wf.write_text(wf.read_text().replace("0.85", "0.80"))
            out = run(repo=repo_copy)
            self.assertEqual(out.returncode, 1, out.stdout)
            self.assertIn("does not state the exit bar", out.stdout)


def main() -> int:
    program = unittest.main(exit=False, verbosity=2)
    return 0 if program.result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
