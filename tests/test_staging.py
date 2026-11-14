# SPDX-License-Identifier: MIT OR Apache-2.0
"""Overlay staging never writes outside the work tree, and unsafe paths are refused before any work."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from helpers import clean_env, cli


def repo_with_symlinked_tests(root, target):
    """One commit whose crate has `tests` as a symlink to `target`; returns (repo, sha)."""
    repo = root / "repo"
    (repo / "toy" / "src").mkdir(parents=True)
    env = dict(clean_env(), GIT_AUTHOR_NAME="T", GIT_AUTHOR_EMAIL="t@e", GIT_COMMITTER_NAME="T", GIT_COMMITTER_EMAIL="t@e",
               GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    git = lambda *a: subprocess.run(["git", "-C", str(repo), "-c", "commit.gpgsign=false", *a], env=env, check=True,
                                    capture_output=True, text=True).stdout.strip()
    git("init", "-q", "-b", "main")
    (repo / "toy" / "src" / "lib.rs").write_text("fn mul(a,b){ a * b }\n")
    os.symlink(target, repo / "toy" / "tests")
    git("add", "-A")
    git("commit", "-q", "-m", "tests is a symlink")
    return repo, git("rev-parse", "HEAD")


class Staging(unittest.TestCase):
    """The local runner refuses symlinks on the overlay path; unsafe crate paths are usage errors."""

    def setUp(self):
        """A scratch area with an `outside` directory that must stay empty."""
        self.root = Path(tempfile.mkdtemp(prefix="bug-age-staging-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.outside = self.root / "outside"
        self.outside.mkdir()
        self.overlay = self.root / "overlay"
        (self.overlay / "tests").mkdir(parents=True)
        (self.overlay / "tests" / "bugage_repro.rs").write_text("// regression test\n")

    def probe(self, repo, sha, path="toy"):
        """Probe one commit with the local runner and a trivial build and test."""
        return cli("probe", "--repo", repo, "--path", path, "--commits", sha, "--overlay", self.overlay, "--runner", "local",
                   "--repeats", "1", "--build", "true", "--test", "true", "--scratch", self.root / "scratch",
                   "--logs", self.root / "logs", check=False)

    def test_symlinked_tests_directory_is_untestable_and_nothing_escapes(self):
        """tests -> outside: the commit is UNTESTABLE with a reason, and outside stays empty."""
        repo, sha = repo_with_symlinked_tests(self.root, str(self.outside))
        out = self.probe(repo, sha)
        self.assertEqual(out.returncode, 0, out.stderr)
        r = json.loads(out.stdout)["results"][0]
        self.assertEqual(r["outcome"], "UNTESTABLE")
        self.assertIn("symlink", r["reason"])
        self.assertEqual(list(self.outside.iterdir()), [], "nothing may be written through the symlink")

    def test_unsafe_crate_paths_are_refused_before_any_work(self):
        """'..', absolute paths and shell metacharacters in --path exit 2 and create no worktree."""
        repo, sha = repo_with_symlinked_tests(self.root, str(self.outside))
        for bad in ("../x", "/etc", "toy/../..", "toy;touch pwned", "toy $(id)", "a b", "toy/./x"):
            with self.subTest(path=bad):
                out = self.probe(repo, sha, path=bad)
                self.assertEqual(out.returncode, 2, out.stderr)
                self.assertIn("crate path", out.stderr)
        self.assertFalse((self.root / "scratch").exists())

    def test_symlink_inside_the_overlay_is_refused(self):
        """An overlay that itself contains a symlink is refused before any work."""
        os.symlink("/etc/passwd", self.overlay / "tests" / "link.rs")
        repo, sha = repo_with_symlinked_tests(self.root, str(self.outside))
        out = self.probe(repo, sha)
        self.assertEqual(out.returncode, 2, out.stderr)
        self.assertIn("is a symlink", out.stderr)



@unittest.skipUnless(os.environ.get("BUG_AGE_DOCKER_TESTS") == "1", "set BUG_AGE_DOCKER_TESTS=1 (needs Docker and the image)")
class DockerBoundary(unittest.TestCase):
    """In Docker, a symlinked tests directory is refused and test code cannot write to the shared caches."""

    def test_shared_caches_stay_clean(self):
        """A commit linking tests -> /cargo is UNTESTABLE; a test writing into /cargo and /rustup fails to."""
        ns = f"t{os.getpid()}"
        root = Path(tempfile.mkdtemp(prefix="bug-age-docker-"))
        self.addCleanup(shutil.rmtree, root, True)
        overlay = root / "overlay"
        (overlay / "tests").mkdir(parents=True)
        (overlay / "tests" / "bugage_repro.rs").write_text("// PLANTED-BY-OVERLAY\n")

        def probe(repo, sha, test):
            out = cli("probe", "--repo", repo, "--path", "toy", "--commits", sha, "--overlay", overlay, "--runner", "docker",
                      "--namespace", ns, "--time-travel-script", "none", "--repeats", "1", "--build", "true", "--test", test,
                      "--scratch", root / "scratch", "--logs", root / "logs")
            return json.loads(out.stdout)["results"][0]

        def planted(volume):
            ls = subprocess.run(["docker", "run", "--rm", "-v", f"{volume}:/v", "bug-age-spike:4", "sh", "-c",
                                 "find /v -maxdepth 3 -name 'PLANTED*' -o -maxdepth 3 -name bugage_repro.rs"],
                                capture_output=True, text=True)
            return ls.stdout.split()
        self.addCleanup(lambda: subprocess.run(["sh", "-c", f"docker volume ls -q --filter name={ns} | xargs -r docker volume rm -f"],
                                               capture_output=True))
        linked, sha = repo_with_symlinked_tests(root / "a", "/cargo")
        (linked / "toy" / "Cargo.lock").write_text("version = 3\n")
        r = probe(linked, sha, "true")
        self.assertEqual(r["outcome"], "UNTESTABLE")
        self.assertIn("symlink", r["reason"])
        plain, sha2 = repo_with_symlinked_tests(root / "b", str(root / "elsewhere"))
        subprocess.run(["git", "-C", str(plain), "rm", "-q", "toy/tests"], env=clean_env(), check=True)
        (plain / "toy" / "Cargo.toml").write_text('[package]\nname = "toy"\nversion = "0.1.0"\nedition = "2021"\n\n[workspace]\n')
        subprocess.run(["git", "-C", str(plain), "-c", "commit.gpgsign=false", "add", "-A"], env=clean_env(), check=True)
        subprocess.run(["git", "-C", str(plain), "-c", "commit.gpgsign=false", "-c", "user.name=T", "-c", "user.email=t@e",
                        "commit", "-q", "-m", "plain"], env=clean_env(), check=True)
        head = subprocess.run(["git", "-C", str(plain), "rev-parse", "HEAD"], env=clean_env(), capture_output=True, text=True).stdout.strip()
        r = probe(plain, head, "touch /cargo/PLANTED-BY-TEST /rustup/PLANTED-BY-TEST")
        self.assertEqual(r["outcome"], "FAIL", "the caches are read-only for test code")
        self.assertEqual(planted(f"bugage-cargo-{ns}"), [])
        self.assertEqual(planted("bugage-rustup"), [])


if __name__ == "__main__":
    unittest.main()
