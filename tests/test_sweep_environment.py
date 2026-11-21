# SPDX-License-Identifier: MIT OR Apache-2.0
"""Build failures that are not the overlay's: refused options, a missing command, a missing module."""
import json
import shutil
import unittest

from helpers import cli
from test_sweep import NONE, OK, overlay, toy_repo


class Environment(unittest.TestCase):
    """The local runner with shell-only build commands, so no toolchain is needed."""

    def setUp(self):
        """A two-commit history (bug, then fix) and its overlay."""
        self.root, self.repo, self.scratch, self.shas = toy_repo([NONE, OK])
        self.addCleanup(shutil.rmtree, self.root, True)
        self.overlay = overlay(self.root, 6)

    def sweep(self, build, *extra):
        """Run sweep with `build` as the build step and `true` as the test; return the process."""
        return cli("sweep", "--repo", self.repo, "--path", "toy", "--overlay", self.overlay, "--runner", "local",
                   "--repeats", "1", "--build", build, "--test", "true", "--scratch", self.scratch,
                   "--logs", self.scratch / "logs", "--fix", self.shas[1], *extra, check=False)

    def test_install_options_are_refused_with_the_local_runner(self):
        """--install and --test-deps would be ignored by the host runner, so they are refused."""
        for flag, value in (("--install", "."), ("--test-deps", "pytest")):
            with self.subTest(flag=flag):
                out = self.sweep("true", "--profile", "python", flag, value)
                self.assertEqual(out.returncode, 2, out.stderr)
                self.assertIn(f"{flag} needs --runner docker", out.stderr)

    def test_a_missing_build_command_stops_the_sweep(self):
        """Exit 127 is the host's problem, not the commit's: an error naming the command, no report."""
        out = self.sweep("bugage-no-such-tool --no-run")
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("build command could not run", out.stderr)
        self.assertIn("bugage-no-such-tool", out.stderr)
        self.assertEqual(out.stdout, "")

    def test_the_logged_command_line_is_not_an_overlay_error(self):
        """A failing build whose command names the overlay file is not blamed on the overlay."""
        out = self.sweep("test -f tests/bugage_repro.rs && exit 3")
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertNotIn("overlay does not compile", out.stderr)
        self.assertIn("test build failed at the fix", out.stderr)
        self.assertIn("build.log", out.stderr)

    def test_a_missing_module_is_not_an_overlay_error(self):
        """Python: the overlay named next to 'No module named' is a missing dependency."""
        out = self.sweep("echo \"tests/bugage_repro_test.py:1: ModuleNotFoundError: No module named 'toy'\"; exit 2",
                         "--profile", "python")
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("test build failed at the fix", out.stderr)

    def test_an_overlay_compile_error_is_still_repro_invalid(self):
        """The marker in the build output itself keeps its meaning."""
        out = self.sweep("echo 'error: tests/bugage_repro.rs:1: cannot find function'; exit 1")
        self.assertEqual(out.returncode, 0, out.stderr)
        report = json.loads(out.stdout)["report"]
        self.assertEqual(report["verdict"], "repro-invalid")
        self.assertEqual(report["results"][-1]["reason"], "test build failed (overlay does not compile here)")


if __name__ == "__main__":
    unittest.main()
