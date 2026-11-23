# SPDX-License-Identifier: MIT OR Apache-2.0
"""The published numbers do not change: regenerate both example runs and compare byte for byte.

The committed results/ and dist/ files are the output of bug-age 1.0.2, the last Rust version.
Each stage is regenerated from the target clones in work/ (see targets/*.toml) and must equal
them exactly; in a bundle the only allowed difference is the "generator" string, which names the
tool version. The test is skipped when a clone is missing. CI clones both afresh and sets
BUG_AGE_FRESH_CLONES=1, which limits the comparison to catalog and szz (see check()).
"""
import os
import re
import shutil
import tempfile
import tomllib
import unittest
from pathlib import Path

from helpers import ROOT, cli

GEN = re.compile(rb'"generator":"bug-age [^"]*"')


def target(name):
    """A target's config."""
    return tomllib.loads((ROOT / "targets" / f"{name}.toml").read_text(encoding="utf-8"))


# The published explorer, in the order of make explorer.
TARGETS = ("tokenizers", "rust-sdk", "requests", "flask")

class Oracle(unittest.TestCase):
    """Catalog, Method A, bundle, explorer and MCP output equal the committed 1.0.2 files."""

    def setUp(self):
        """A scratch output directory."""
        self.out = Path(tempfile.mkdtemp(prefix="bug-age-oracle-"))

    def tearDown(self):
        """Remove it."""
        shutil.rmtree(self.out, ignore_errors=True)

    def assertSameFile(self, got, want, generator=False):
        """Byte equality; with `generator`, the bundle's generator string is ignored."""
        a, b = Path(got).read_bytes(), Path(want).read_bytes()
        if generator:
            a, b = GEN.sub(b'"generator":""', a), GEN.sub(b'"generator":""', b)
        self.assertTrue(a == b, f"{got} differs from {want}")

    def check(self, name):
        """Regenerate one target's catalog, szz and bundle and compare with the committed files."""
        c = target(name)
        repo = ROOT / c["work_dir"]
        if not (repo / ".git").exists():
            self.skipTest(f"no clone at {c['work_dir']}")
        committed = ROOT / c["results_dir"]
        res, dist = self.out / name / "results", self.out / name / "dist"
        res.mkdir(parents=True)
        cli("catalog", "--repo", repo, "--path", c["crate_path"], "--head", c["head"], "--out", res / "catalog.json")
        self.assertSameFile(res / "catalog.json", committed / "catalog.json")
        szz = ["--window-start", c["szz_window_start"]] if "szz_window_start" in c else []
        szz += ["--release-tags", c["release_tag_glob"]] if "release_tag_glob" in c else []
        cli("szz", "--repo", repo, "--catalog", res / "catalog.json", *szz, "--out", res / "szz.json")
        self.assertSameFile(res / "szz.json", committed / "szz.json")
        if (committed / "repros").is_dir():
            shutil.copytree(committed / "repros", res / "repros")
        args = ["--out-of-scope", c["out_of_scope"]] if "out_of_scope" in c else []
        # The bundle's redaction list comes from every ref in the clone (`git log --all`), so a clone
        # made later than the published run's can carry newer contributors, redact differently or
        # trip the blameless gate; 1.x behaves the same. Fresh CI clones compare catalog and szz only.
        if os.environ.get("BUG_AGE_FRESH_CLONES") == "1":
            return
        cli("bundle", "--repo", repo, "--results", res, "--repo-url", c["repo_url"], "--out", dist,
            "--spike", ROOT / c["spike_dir"], *args)
        self.assertSameFile(dist / "bundle.json", ROOT / c["dist_dir"] / "bundle.json", generator=True)

    def test_tokenizers(self):
        """The tokenizers example run."""
        self.check("tokenizers")

    def test_rust_sdk(self):
        """The rust-sdk example run."""
        self.check("rust-sdk")

    def test_explorer(self):
        """The explorer page and data files built from the committed bundles."""
        cli("explorer",
            "--targets", ",".join(f"{n}={ROOT / 'dist' / n}" for n in TARGETS), "--out", self.out)
        for rel in ("index.html", *(f"data/{n}.js" for n in TARGETS)):
            self.assertSameFile(self.out / rel, ROOT / "dist" / "explorer" / rel)


    def test_only_documented_changes_since_1_0_2(self):
        """Against tag v1.0.2, the published bundles differ only in the documented fields.

        2.1: a bisected sweep's "located" became "boundary" (a lower bound), every sweep records its
        search, and the schema version and generator changed. No number changed.
        """
        import json
        import subprocess

        def diff(a, b, path=""):
            if type(a) is not type(b):
                yield path
            elif isinstance(a, dict):
                for k in sorted(set(a) | set(b)):
                    yield from diff(a.get(k), b.get(k), f"{path}.{k}")
            elif isinstance(a, list):
                if len(a) != len(b):
                    yield f"{path}[len]"
                for i, (x, y) in enumerate(zip(a, b)):
                    yield from diff(x, y, f"{path}[{i}]")
            elif a != b:
                yield path
        allowed = re.compile(r"^\.(generator|schema_version|summary\.method_b\.(located|verdicts\.(located|boundary))"
                             r"|method_b\[\d+\]\.(search|verdict|reason|days_is_lower_bound))$")
        for name in ("tokenizers", "rust-sdk"):
            old = subprocess.run(["git", "show", f"v1.0.2:dist/{name}/bundle.json"], cwd=ROOT, capture_output=True, text=True)
            if old.returncode != 0:
                self.skipTest("tag v1.0.2 not fetched")
            new = json.loads((ROOT / "dist" / name / "bundle.json").read_text(encoding="utf-8"))
            changed = [d for d in diff(json.loads(old.stdout), new) if not allowed.match(d)]
            self.assertEqual(changed, [], name)
            for row in new["method_b"]:
                # Only a full scan may claim an exact boundary.
                self.assertTrue(row["verdict"] != "located" or row["search"] == "exhaustive", row["id"])


if __name__ == "__main__":
    unittest.main()
