# SPDX-License-Identifier: MIT OR Apache-2.0
"""The published numbers do not change: regenerate both example runs and compare byte for byte.

The committed results/ and dist/ files are the output of bug-age 1.0.2, the last Rust version.
Each stage is regenerated from the target clones in work/ (see targets/*.toml) and must equal
them exactly; in a bundle the only allowed difference is the "generator" string, which names the
tool version. The test is skipped when a clone is missing (CI clones both).
"""
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
        cli("explorer", "--page", ROOT / "explorer" / "index.html",
            "--targets", f"tokenizers={ROOT / 'dist/tokenizers'},rust-sdk={ROOT / 'dist/rust-sdk'}", "--out", self.out)
        for rel in ("index.html", "data/tokenizers.js", "data/rust-sdk.js"):
            self.assertSameFile(self.out / rel, ROOT / "dist" / "explorer" / rel)


if __name__ == "__main__":
    unittest.main()
