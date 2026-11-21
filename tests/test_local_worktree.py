# SPDX-License-Identifier: MIT OR Apache-2.0
"""The local runner leaves the repository's worktrees as it found them: after success, failure or Ctrl-C."""
import os
import shutil
import signal
import subprocess
import sys
import time
import unittest

from helpers import ROOT, clean_env, cli
from test_sweep import NONE, OK, overlay, toy_repo


class LocalWorktree(unittest.TestCase):
    """Shell-only build and test commands, so no toolchain is needed."""

    def setUp(self):
        """A two-commit history and its overlay."""
        self.root, self.repo, self.scratch, self.shas = toy_repo([NONE, OK])
        self.addCleanup(shutil.rmtree, self.root, True)
        self.overlay = overlay(self.root, 6)

    def args(self, command, build, *extra):
        """sweep or probe flags with the local runner."""
        target = ["--fix", self.shas[1]] if command == "sweep" else ["--commits", ",".join(self.shas)]
        return [command, "--repo", self.repo, "--path", "toy", "--overlay", self.overlay, "--runner", "local",
                "--repeats", "1", "--build", build, "--test", "true", "--scratch", self.scratch,
                "--logs", self.scratch / "logs", *target, *extra]

    def assertClean(self):
        """Only the repository's own worktree is registered, and the scratch checkout is gone."""
        listing = subprocess.run(["git", "-C", str(self.repo), "worktree", "list", "--porcelain"], env=clean_env(),
                                 capture_output=True, text=True, check=True).stdout
        self.assertEqual(listing.count("worktree "), 1, listing)
        self.assertFalse((self.scratch / "local-wt").exists())

    def test_finished_sweep(self):
        """A sweep that reaches a verdict."""
        self.assertEqual(cli(*self.args("sweep", "true"), check=False).returncode, 0)
        self.assertClean()

    def test_failed_sweep(self):
        """A sweep stopped by an error."""
        self.assertEqual(cli(*self.args("sweep", "bugage-no-such-tool"), check=False).returncode, 1)
        self.assertClean()

    def test_finished_probe(self):
        """A probe of every commit."""
        self.assertEqual(cli(*self.args("probe", "true"), check=False).returncode, 0)
        self.assertClean()

    def test_interrupted_sweep(self):
        """Ctrl-C during a build step: the step is stopped and the worktree removed."""
        marker = self.root / "build-ran"
        proc = subprocess.Popen([sys.executable, "-m", "bug_age", *map(str, self.args("sweep", f"echo $$ > {marker}; exec sleep 60"))],
                                cwd=ROOT, env=clean_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 30
        while not (marker.exists() and marker.read_text().strip()) and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertTrue(marker.exists(), "the build step never started")
        proc.send_signal(signal.SIGINT)
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
            self.fail("bug-age did not stop after SIGINT")
        self.assertNotEqual(proc.returncode, 0)
        with self.assertRaises(ProcessLookupError, msg="the build step outlived bug-age"):
            os.kill(int(marker.read_text()), 0)
        self.assertClean()


if __name__ == "__main__":
    unittest.main()
