# SPDX-License-Identifier: MIT OR Apache-2.0
"""Commit subjects in a bundle stay within the schema's 100 characters after redaction."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from helpers import cli, commit, run_git


class LongRedactedSubject(unittest.TestCase):
    """A 99-character subject naming a short-named contributor is redacted, then cut to 100 characters."""

    def test_bundle_is_written_and_valid(self):
        """Before the cut moved after redaction, "[redacted]" pushed it past 100 and the bundle was refused."""
        d = Path(tempfile.mkdtemp(prefix="bug-age-subj-"))
        self.addCleanup(shutil.rmtree, d, True)
        repo = d / "repo"
        repo.mkdir()
        run_git(repo, ["init", "-q"], "2025-01-01T00:00:00Z")
        commit(repo, "pkg/calc.py", "def mul(a, b):\n    return a + b\n", "init", "2025-01-01T00:00:00Z")
        # A contributor whose name is shorter than "[redacted]", named at the end of a 99-character subject.
        subject = "Fix mul returning the sum " + "x" * (99 - 26 - len(" Al Bo")) + " Al Bo"
        self.assertEqual(len(subject), 99)
        (repo / "pkg" / "calc.py").write_text("def mul(a, b):\n    return a * b\n")
        run_git(repo, ["add", "-A"], "2025-02-01T00:00:00Z")
        run_git(repo, ["commit", "-q", "--author", "Al Bo <al@example.invalid>", "-m", subject], "2025-02-01T00:00:00Z")
        (d / "res").mkdir()
        cli("catalog", "--repo", repo, "--path", "pkg", "--profile", "python", "--out", d / "res" / "catalog.json")
        cli("szz", "--repo", repo, "--catalog", d / "res" / "catalog.json", "--out", d / "res" / "szz.json")
        cli("bundle", "--repo", repo, "--results", d / "res", "--repo-url", "https://example.invalid/calc",
            "--out", d / "dist", "--spike", d / "no-spike")
        b = json.loads((d / "dist" / "bundle.json").read_text())
        subjects = [c["subject"] for c in b["commits"].values()]
        fixed = next(s for s in subjects if s.startswith("Fix mul"))
        self.assertTrue(fixed.endswith("x"), fixed)          # the name is gone, no half placeholder is left
        self.assertNotIn("Al Bo", fixed)
        self.assertTrue(all(len(s) <= 100 for s in subjects))


if __name__ == "__main__":
    unittest.main()
