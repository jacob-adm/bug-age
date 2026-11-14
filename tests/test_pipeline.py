# SPDX-License-Identifier: MIT OR Apache-2.0
"""The pipeline reuses an output only when it belongs to this run, and the bundle only reads those.

Runs `bug-age pipeline` on the tokenizers example from a scratch directory that links the clone
and copies the committed results. Skipped when the clone in work/tokenizers is missing.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

from helpers import ROOT, clean_env

CLONE = ROOT / "work" / "tokenizers"


@unittest.skipUnless((CLONE / ".git").exists(), "needs the tokenizers clone in work/tokenizers")
class Pipeline(unittest.TestCase):
    """Reuse is bound to the pinned head and the overlay; skipped or stale stages add no data."""

    def setUp(self):
        """A scratch working directory laid out like the repository for one target."""
        self.d = Path(tempfile.mkdtemp(prefix="bug-age-pipeline-"))
        self.addCleanup(shutil.rmtree, self.d, True)
        (self.d / "work").mkdir()
        (self.d / "work" / "tokenizers").symlink_to(CLONE)
        shutil.copytree(ROOT / "results" / "tokenizers" / "repros", self.d / "results" / "tokenizers" / "repros")
        shutil.copytree(ROOT / "spike" / "results", self.d / "spike" / "results")
        shutil.copytree(ROOT / "spike" / "results-timetravel", self.d / "spike" / "results-timetravel")
        (self.d / "targets").mkdir()
        self.cfg = tomllib.loads((ROOT / "targets" / "tokenizers.toml").read_text())

    def run_pipeline(self, *args, head=None, edit=None):
        """Run the pipeline (optionally re-pinned to `head`); return (exit code, stages by name, bundle)."""
        text = (ROOT / "targets" / "tokenizers.toml").read_text()
        if head:
            text = text.replace(self.cfg["head"], head)
        if edit:
            text = edit(text)
        (self.d / "targets" / "tokenizers.toml").write_text(text)
        out = subprocess.run([sys.executable, "-m", "bug_age", "pipeline", "targets/tokenizers.toml", *args],
                             cwd=self.d, env=dict(clean_env(), PYTHONPATH=str(ROOT)), capture_output=True, text=True)
        stages = {s["stage"]: s for s in json.loads((self.d / "results" / "tokenizers" / "pipeline.json").read_text())["stages"]}
        bundle_file = self.d / "dist" / "tokenizers" / "bundle.json"
        return out.returncode, stages, json.loads(bundle_file.read_text()) if bundle_file.exists() else None

    def test_unchanged_inputs_reproduce_the_published_bundle(self):
        """At the pinned head every reused output is verified and the bundle equals the committed one."""
        code, stages, _ = self.run_pipeline()
        self.assertEqual(code, 0, stages)
        self.assertEqual(stages["feasibility (baseline)"]["status"], "REUSED")
        self.assertEqual(stages["Method B (repro sweeps)"]["status"], "REUSED")
        # A fresh clone (CI) can carry newer contributors, so the bytes are compared on the recording clone only.
        if os.environ.get("BUG_AGE_FRESH_CLONES") != "1":
            self.assertEqual((self.d / "dist" / "tokenizers" / "bundle.json").read_bytes(),
                             (ROOT / "dist" / "tokenizers" / "bundle.json").read_bytes())

    def test_skipped_feasibility_adds_no_data(self):
        """--skip-feasibility: NOT TESTED in the stage report and no feasibility data in the bundle."""
        code, stages, bundle = self.run_pipeline("--skip-feasibility")
        self.assertEqual(code, 0, stages)
        self.assertEqual(stages["feasibility (baseline)"]["status"], "NOT TESTED")
        self.assertEqual(bundle["feasibility"], {"baseline": None, "time_travel": None})
        cover = {r["stage"]: r["status"] for r in bundle["coverage"]}
        self.assertEqual(cover["Historical buildability"], "NOT TESTED")

    def test_repinned_head_never_reuses_outputs_of_the_old_head(self):
        """At another head the old feasibility reports are refused as stale and stay out of the bundle."""
        older = subprocess.run(["git", "-C", str(CLONE), "rev-parse", f"{self.cfg['head']}~50"], env=clean_env(),
                               capture_output=True, text=True, check=True).stdout.strip()
        code, stages, bundle = self.run_pipeline(head=older)
        self.assertNotEqual(code, 0)
        self.assertEqual(stages["feasibility (baseline)"]["status"], "FAILED")
        self.assertIn("stale report: made at head fb49a29223", stages["feasibility (baseline)"]["reason"])
        self.assertEqual(bundle["subject"]["head"], older)
        self.assertEqual(bundle["feasibility"], {"baseline": None, "time_travel": None})
        # Sweeps whose fix is not in the older history are refused, and none of them reach the bundle.
        if stages["Method B (repro sweeps)"]["status"] == "FAILED":
            self.assertIn("is not in the history of the pinned head", stages["Method B (repro sweeps)"]["reason"])
            self.assertEqual(bundle["method_b"], [])


    def test_same_head_drift_is_never_reused(self):
        """At the pinned head, a different sample count, an edited report or other sweep settings are stale."""
        import hashlib
        code, stages, bundle = self.run_pipeline(edit=lambda t: t.replace("samples = 20", "samples = 1"))
        self.assertEqual(stages["feasibility (baseline)"]["status"], "FAILED")
        self.assertIn("made with --samples 20, the config asks for 1", stages["feasibility (baseline)"]["reason"])
        self.assertEqual(bundle["feasibility"], {"baseline": None, "time_travel": None})
        # An edited report no longer matches the hash its receipt recorded.
        report = self.d / "spike" / "results" / "report.json"
        report.write_text(report.read_text().replace('"NO-GO"', '"GO"', 1))
        _, stages, _ = self.run_pipeline()
        self.assertIn("does not match the hash recorded in its receipt", stages["feasibility (baseline)"]["reason"])
        # A sweep made with other settings, its receipt hash updated to match, is still stale.
        sweep_dir = self.d / "results" / "tokenizers" / "repros" / "c046da7679"
        sweep = json.loads((sweep_dir / "sweep.json").read_text())
        sweep["repeats"] = 1
        text = json.dumps(sweep)
        (sweep_dir / "sweep.json").write_text(text)
        receipt = json.loads((sweep_dir / "sweep.json.receipt.json").read_text())
        receipt["report_sha256"] = hashlib.sha256(text.encode()).hexdigest()
        (sweep_dir / "sweep.json.receipt.json").write_text(json.dumps(receipt))
        _, stages, bundle = self.run_pipeline()
        self.assertEqual(stages["Method B (repro sweeps)"]["status"], "FAILED")
        self.assertIn("made with repeats 1, this run would use 3", stages["Method B (repro sweeps)"]["reason"])
        self.assertEqual(bundle["method_b"], [])

    def test_receipts_without_an_image_recipe_are_disclosed(self):
        """Receipts made before the recipe was recorded are reused, and the stage report says so."""
        code, stages, _ = self.run_pipeline()
        self.assertEqual(stages["feasibility (baseline)"]["status"], "REUSED")
        self.assertIn("image recipe not recorded", stages["feasibility (baseline)"]["reason"])
        self.assertIn("image recipe not recorded for 6", stages["Method B (repro sweeps)"]["reason"])


if __name__ == "__main__":
    unittest.main()
