# SPDX-License-Identifier: MIT OR Apache-2.0
"""Commit runners: execution environments for testing one commit with a regression-test overlay.

`Docker` is the real runner: each commit's tree is copied into a volume with `git archive` (host
bind mounts served stale trees), the toolchain is date-matched, lockfile-less commits resolve
against a time-travel index, and build/test run with `--network none`. `Local` uses the host
toolchain in a git worktree; it exists so the sweep logic can be tested end to end without Docker,
and is not hermetic.
"""
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

from ._compat import lines, round1, trim
from .git import GitError, git, run as git_run

PASS, FAIL, UNTESTABLE, FLAKY = "PASS", "FAIL", "UNTESTABLE", "FLAKY"
# Rust's Debug names of the outcomes, used in reason and confirmation texts.
DEBUG = {PASS: "Pass", FAIL: "Fail", UNTESTABLE: "Untestable", FLAKY: "Flaky"}


class RunnerError(RuntimeError):
    """The harness could not prepare or run a commit (not a test result)."""


class Spec:
    """What to test: repository, crate path, overlay, build and test commands, repeats and directories."""

    def __init__(self, repo, crate_path, overlay, build, test, repeats, scratch, logs):
        self.repo, self.crate_path, self.overlay = Path(repo), crate_path, Path(overlay)
        self.build, self.test, self.repeats = build, test, repeats
        self.scratch, self.logs = Path(scratch), Path(logs)


def toolchain_for(commit_unix, rust_version=None):
    """Date-matched stable toolchain: latest release >= 14 days before the commit (one minor every
    42 days since 1.0), raised to the crate's declared rust-version."""
    rust_1_0 = 1_431_648_000
    # Rust's integer division truncates toward zero.
    num = commit_unix - 14 * 86_400 - rust_1_0
    minor = abs(num) // (42 * 86_400) * (1 if num >= 0 else -1)
    if rust_version:
        m = re.fullmatch(r"1\.([+-]?[0-9]+)(\..*)?", rust_version)
        if m:
            minor = max(minor, int(m.group(1)))
    return f"1.{minor}"


def bucketed(toolchain, bucket):
    """Round the minor version up to a multiple of `bucket`, so nearby commits share a build cache."""
    m = re.fullmatch(r"1\.([+-]?[0-9]+)", toolchain)
    if bucket > 1 and m:
        minor = int(m.group(1))
        return f"1.{_div(minor + bucket - 1, bucket) * bucket}"
    return toolchain


def _div(a, b):
    """Integer division truncating toward zero, as Rust's `/` on i64."""
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b >= 0) else -q


def rust_version(repo, sha, crate_path):
    """The `rust-version` declared in the crate's Cargo.toml at `sha`, if any."""
    try:
        manifest = git(repo, ["show", f"{sha}:{crate_path}/Cargo.toml"])
    except GitError:
        return None
    for line in lines(manifest):
        t = trim(line)
        if not t.startswith("rust-version"):
            continue
        rest = trim(t[len("rust-version"):])
        if rest.startswith("="):
            return trim(rest[1:]).strip('"')
    return None


def has_lockfile(repo, sha, crate_path):
    """True if a Cargo.lock exists at `sha` in the crate directory or the repository root."""
    return any(git_run(repo, ["cat-file", "-e", obj], check=False).returncode == 0
               for obj in (f"{sha}:{crate_path}/Cargo.lock", f"{sha}:Cargo.lock"))


def run_logged(argv, log, stdin=None, cwd=None, env=None):
    """Run a command, write `$ command` plus its output to `log`; return (exit code, seconds to 0.1).

    A process killed by a signal reports -1, as Rust's `status.code().unwrap_or(-1)`.
    """
    t0 = time.monotonic()
    try:
        out = subprocess.run(argv, input=stdin, stdin=None if stdin is not None else subprocess.DEVNULL,
                             capture_output=True, cwd=cwd, env=env)
    except OSError as exc:
        raise RunnerError(f"spawn failed: {exc}") from exc
    seconds = round1(time.monotonic() - t0)
    log = Path(log)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_bytes(f"$ {shlex.join(argv)}\n".encode() + out.stdout + out.stderr)
    return (out.returncode if out.returncode >= 0 else -1), seconds


def copy_tree(src, dst):
    """Copy every file under `src` into `dst`, creating directories, overwriting files."""
    for entry in sorted(Path(src).iterdir()):
        target = Path(dst) / entry.name
        if entry.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            copy_tree(entry, target)
        else:
            shutil.copyfile(entry, target)


class Local:
    """Host runner: checks commits out in a git worktree and uses the host toolchain. Not hermetic."""

    name = "local"

    def __init__(self, spec):
        self.wt = spec.scratch / "local-wt"

    def stage(self, spec, sha):
        """Check `sha` out into a fresh worktree and copy the overlay into the crate."""
        git_run(spec.repo, ["worktree", "remove", "--force", str(self.wt)], check=False)
        shutil.rmtree(self.wt, ignore_errors=True)
        git(spec.repo, ["worktree", "add", "--force", "--detach", str(self.wt), sha])
        copy_tree(spec.overlay, self.wt / spec.crate_path)
        return "host"

    def exec(self, spec, cmd, network, log):
        """Run `cmd` with sh in the crate directory of the worktree."""
        # The full caller environment, as the Rust runner passed it, plus the cargo settings.
        env = dict(os.environ, CARGO_TARGET_DIR=str(spec.scratch / "local-target"), CARGO_TERM_COLOR="never")
        return run_logged(["sh", "-c", cmd], log, cwd=self.wt / spec.crate_path, env=env)

    def fallback_toolchain(self, spec, log):
        """The host toolchain has no fallback."""
        return None


KEEP_TARGETS = 2
SRC = "bugage-src"
INDEX = "bugage-index"


class Docker:
    """Hermetic runner: per-commit source volume, date-matched toolchain, offline build and test."""

    name = "docker"

    def __init__(self, image, time_travel_script=None, namespace="", bucket=0):
        self.image, self.time_travel_script = image, time_travel_script
        self.namespace, self.bucket = namespace, bucket
        self.toolchain = self.exact_toolchain = ""
        self.recent, self.unavailable = [], []

    def v(self, base):
        """Volume name in this runner's namespace."""
        return f"{base}{self.namespace}"

    def target_volume(self, toolchain):
        """Build-cache volume for one toolchain."""
        return f"bugage-target{self.namespace}-{toolchain}"

    def docker(self, args, stdin, log):
        """Run docker with `args`, logged."""
        return run_logged(["docker", *args], log, stdin=stdin)

    def install(self, spec, log):
        """Install the current toolchain (serialised across parallel sweeps by a lock file)."""
        cmd = (f"flock /rustup/.bug-age-install.lock rustup toolchain install {self.toolchain} "
               f"--profile minimal --no-self-update")
        code, _ = self.exec(spec, cmd, True, log)
        if code != 0:
            raise RunnerError(f"toolchain {self.toolchain} could not be installed")

    def untar_into(self, volume, d, tar, log):
        """Extract a tar stream into directory `d` of a volume."""
        mount = f"{self.v(volume)}:/{volume}"
        code, _ = self.docker(["run", "-i", "--rm", "-v", mount, self.image, "sh", "-c",
                               f"mkdir -p {d} && tar -x -m --no-same-owner -C {d}"], tar, log)
        if code != 0:
            raise RunnerError(f"harness: untar into {volume}:{d} failed (see {log})")

    def evict_build_caches(self, logs):
        """Keep the build caches of the two most recent toolchains; remove the others."""
        self.recent = [t for t in self.recent if t != self.toolchain] + [self.toolchain]
        if len(self.recent) > KEEP_TARGETS:
            self.recent.pop(0)
        prefix = f"bugage-target{self.namespace}-"
        keep = [self.target_volume(t) for t in self.recent]
        try:
            listed = subprocess.run(["docker", "volume", "ls", "-q", "--filter", f"name={prefix}"], capture_output=True)
        except OSError as exc:
            raise RunnerError(str(exc)) from exc
        stale = [v for v in lines(listed.stdout.decode("utf-8", "replace"))
                 if v.startswith(prefix) and v[len(prefix):].startswith("1.") and v not in keep]
        if stale:
            self.docker(["volume", "rm", "-f", *stale], None, Path(logs) / "stage-evict.log")

    def _tar_dir(self, d):
        """A tar stream of directory `d`, without macOS extended attributes."""
        out = subprocess.run(["tar", "--no-xattrs", "-C", str(d), "-cf", "-", "."], capture_output=True,
                             env=dict(os.environ, COPYFILE_DISABLE="1"))
        return out.stdout

    def time_travel(self, spec, sha, script):
        """Build a registry index as of the commit's date and point cargo at it."""
        short = sha[:12]
        tree, out = spec.scratch / "tt-tree" / short, spec.scratch / "tt-index" / short
        shutil.rmtree(tree, ignore_errors=True)
        shutil.rmtree(out, ignore_errors=True)
        tree.mkdir(parents=True)
        archive = git_run(spec.repo, ["archive", "--format=tar", sha], check=False).stdout
        subprocess.run(["tar", "-x", "-C", str(tree)], input=archive)
        cutoff = trim(git(spec.repo, ["show", "-s", "--format=%ct", sha]))
        log = spec.logs / short / "time-travel.log"
        code, _ = run_logged([sys.executable, "-I", str(script), str(tree), spec.crate_path, cutoff,
                              str(spec.scratch / "index-cache"), str(out)], log)
        if code != 0:
            raise RunnerError(f"harness: time-travel index failed (see {log})")
        packed = self._tar_dir(out)
        shutil.rmtree(tree, ignore_errors=True)
        shutil.rmtree(out, ignore_errors=True)
        reset = (f"rm -rf /{INDEX}/current && mkdir -p /cargo/registry/index && find /cargo/registry/index -mindepth 1 -maxdepth 1 "
                 f"! -name 'github.com-*' ! -name 'index.crates.io-*' -exec rm -rf {{}} +")
        self.docker(["run", "--rm", "-v", f"{self.v(INDEX)}:/{INDEX}", "-v", f"{self.v('bugage-cargo')}:/cargo",
                     self.image, "sh", "-c", reset], None, spec.logs / short / "stage-index-reset.log")
        self.untar_into(INDEX, f"/{INDEX}/current", packed, spec.logs / short / "stage-index.log")
        cfg = (f'[source.crates-io]\\nreplace-with = \\"tt\\"\\n[source.tt]\\nregistry = \\"file:///{INDEX}/current\\"\\n')
        write = f'mkdir -p /{SRC}/.cargo && printf "{cfg}" > /{SRC}/.cargo/config'
        code, _ = self.docker(["run", "--rm", "-v", f"{self.v(SRC)}:/{SRC}", self.image, "sh", "-c", write], None,
                              spec.logs / short / "stage-config.log")
        if code != 0:
            raise RunnerError("harness: writing .cargo/config failed")

    def fallback_toolchain(self, spec, log):
        """Switch to the exact date-matched toolchain after a build failure under a bucketed one."""
        if self.toolchain == self.exact_toolchain:
            return None
        self.toolchain = self.exact_toolchain
        try:
            self.evict_build_caches(Path(log).parent)
            self.install(spec, log)
        except RunnerError:
            return None
        return self.toolchain

    def stage(self, spec, sha):
        """Prepare the source volume for `sha` with the overlay, dependencies and toolchain."""
        logs = spec.logs / sha[:12]
        self.docker(["volume", "rm", "-f", self.v(SRC)], None, logs / "stage-reset.log")
        archive = git_run(spec.repo, ["archive", "--format=tar", sha], check=False)
        if archive.returncode != 0:
            raise RunnerError(f"harness: git archive {sha} failed")
        self.untar_into(SRC, f"/{SRC}", archive.stdout, logs / "stage-src.log")
        self.untar_into(SRC, f"/{SRC}/{spec.crate_path}", self._tar_dir(spec.overlay), logs / "stage-overlay.log")
        if not has_lockfile(spec.repo, sha, spec.crate_path) and self.time_travel_script is not None:
            self.time_travel(spec, sha, self.time_travel_script)
        ct = int(trim(git(spec.repo, ["show", "-s", "--format=%ct", sha])))
        self.exact_toolchain = toolchain_for(ct, rust_version(spec.repo, sha, spec.crate_path))
        self.toolchain = bucketed(self.exact_toolchain, self.bucket)
        if self.toolchain in self.unavailable:
            self.toolchain = self.exact_toolchain
        self.evict_build_caches(logs)
        try:
            self.install(spec, logs / "toolchain.log")
            return self.toolchain
        except RunnerError:
            if self.toolchain == self.exact_toolchain:
                raise RunnerError(f"toolchain {self.toolchain} could not be installed") from None
        # The bucket's toolchain is not released yet: use the exact one.
        self.unavailable.append(self.toolchain)
        self.toolchain = self.exact_toolchain
        self.evict_build_caches(logs)
        self.install(spec, logs / "toolchain-exact.log")
        return self.toolchain

    def exec(self, spec, cmd, network, log):
        """Run `cmd` in the crate directory of the source volume; offline unless `network`."""
        args = ["run", "--rm"]
        if not network:
            args += ["--network", "none", "-e", "CARGO_NET_OFFLINE=true"]
        args += ["-v", f"{self.v(SRC)}:/{SRC}", "-v", f"{self.v(INDEX)}:/{INDEX}",
                 "-v", f"{self.target_volume(self.toolchain)}:/target", "-v", "bugage-rustup:/rustup",
                 "-v", f"{self.v('bugage-cargo')}:/cargo", "-e", "CARGO_TARGET_DIR=/target", "-e", "CARGO_TERM_COLOR=never",
                 "-e", f"RUSTUP_TOOLCHAIN={self.toolchain}", "-w", f"/{SRC}/{spec.crate_path}", self.image, "sh", "-c", cmd]
        return self.docker(args, None, log)
