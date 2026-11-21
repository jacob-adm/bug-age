# SPDX-License-Identifier: MIT OR Apache-2.0
"""Which A-checks are stale after Method A changes: no Docker, no git, only the stored files."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from bug_age.repros import stale_achecks

FIX_A, FIX_B, FIX_C = "a" * 40, "b" * 40, "c" * 40
OLD, NEW, PARENT = "1" * 40, "2" * 40, "9" * 40


class StaleAchecks(unittest.TestCase):
    """A results directory with three regression tests."""

    def setUp(self):
        self.res = Path(tempfile.mkdtemp(prefix="bug-age-stale-"))
        self.addCleanup(shutil.rmtree, self.res, True)
        for fix in (FIX_A, FIX_B, FIX_C):
            (self.res / "repros" / fix[:10] / "overlay").mkdir(parents=True)

    def szz(self, nominees):
        """Write szz.json whose fixes have the given primary nominee (None: no nominee)."""
        bugs = [{"fix": fix, "nominees": [{"sha": sha}] if sha else []} for fix, sha in nominees.items()]
        (self.res / "szz.json").write_text(json.dumps({"bugs": bugs}))

    def acheck(self, fix, nominee):
        """Write the A-check of `fix` as having probed `nominee` and its parent."""
        results = [{"sha": PARENT, "outcome": "PASS"}, {"sha": nominee, "outcome": "FAIL"}]
        (self.res / "repros" / fix[:10] / "acheck.json").write_text(json.dumps({"results": results}))

    def test_changed_and_missing_achecks_are_stale(self):
        self.szz({FIX_A: NEW, FIX_B: OLD, FIX_C: NEW})
        self.acheck(FIX_A, OLD)  # nominee changed
        self.acheck(FIX_B, OLD)  # unchanged
        self.assertEqual(stale_achecks(self.res), [FIX_A[:10], FIX_C[:10]])  # C never probed

    def test_a_fix_without_a_nominee_needs_no_acheck(self):
        self.szz({FIX_A: None, FIX_B: OLD, FIX_C: OLD})
        self.acheck(FIX_B, OLD)
        self.acheck(FIX_C, OLD)
        self.assertEqual(stale_achecks(self.res), [])

    def test_nothing_to_check_without_method_a(self):
        self.assertEqual(stale_achecks(self.res), [])


if __name__ == "__main__":
    unittest.main()
