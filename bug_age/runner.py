# SPDX-License-Identifier: MIT OR Apache-2.0
"""Commit runners: execution environments for testing one commit with a regression-test overlay.

`Docker` is the real runner: each commit's tree is copied into a volume with `git archive` (host
bind mounts served stale trees), the toolchain is date-matched, lockfile-less commits resolve
against a time-travel index, and build/test run with `--network none`. `Local` uses the host
toolchain in a git worktree; it exists so the sweep logic can be tested end to end without Docker,
and is not hermetic.
"""
import hashlib
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from ._compat import lines, round1, trim
from .git import GitError, git, run as git_run

PASS, FAIL, UNTESTABLE, FLAKY = "PASS", "FAIL", "UNTESTABLE", "FLAKY"
# Rust's Debug names of the outcomes, used in reason and confirmation texts.
DEBUG = {PASS: "Pass", FAIL: "Fail", UNTESTABLE: "Untestable", FLAKY: "Flaky"}


class RunnerError(RuntimeError):
    """The harness could not prepare or run a commit (not a test result)."""


# A path inside the repository or the overlay: relative, plain characters, no `..`. It is used to
# build file system paths and Docker arguments, so anything else is refused before any work.
_SAFE_PATH = re.compile(r"[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*")


def check_path(rel, what):
    """Return `rel` if it is a safe relative path ("." allowed for the root); else raise ValueError."""
    if rel == "." or (_SAFE_PATH.fullmatch(rel) and ".." not in rel.split("/") and "." not in rel.split("/")):
        return rel
    raise ValueError(f"{what} {rel!r} must be a relative path of letters, digits, '.', '_', '-' and '/', without '..'")


def overlay_files(overlay):
    """Every file in the overlay as a checked relative path; symlinks in the overlay are refused."""
    out = []
    for dirpath, dirs, files in os.walk(overlay):
        for name in dirs + files:
            p = Path(dirpath) / name
            if p.is_symlink():
                raise ValueError(f"overlay entry {p} is a symlink")
        for name in files:
            out.append(check_path(os.path.relpath(Path(dirpath) / name, overlay).replace(os.sep, "/"), "overlay file"))
    return sorted(out)


class Spec:
    """What to test: repository, crate path, overlay, build and test commands, repeats and directories."""

    def __init__(self, repo, crate_path, overlay, build, test, repeats, scratch, logs, step_timeout=3600):
        self.repo, self.crate_path, self.overlay = Path(repo), check_path(crate_path, "crate path"), Path(overlay)
        self.overlay_files = overlay_files(self.overlay)
        self.build, self.test, self.repeats = build, test, repeats
        self.scratch, self.logs = Path(scratch), Path(logs)
        self.step_timeout = step_timeout  # seconds a fetch, build or test step may run


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


TIMED_OUT = -2           # exit recorded for a step stopped at its time limit (-1 is a signal, as in 1.x)
LOG_CAP = 8 * 1024 * 1024  # bytes of output kept per step: the first and the last half


def run_logged(argv, log, stdin=None, cwd=None, env=None, timeout=None, on_timeout=None):
    """Run a command, write `$ command` plus its output to `log`; return (exit code, seconds to 0.1).

    A process killed by a signal reports -1, as Rust's `status.code().unwrap_or(-1)`. With
    `timeout` (seconds), the command's whole process group is killed when it runs longer, then
    `on_timeout()` runs (to stop work outside the group, e.g. a container), and the exit is
    TIMED_OUT. Output is streamed and capped at LOG_CAP bytes: the first and the last half are
    kept and the number of bytes dropped is noted, so an endless writer cannot fill memory or disk.
    """
    t0 = time.monotonic()
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=cwd, env=env,
                                start_new_session=True)
    except OSError as exc:
        raise RunnerError(f"spawn failed: {exc}") from exc
    half = LOG_CAP // 2
    head, tail, dropped = bytearray(), bytearray(), [0]

    def read():
        # Keep exactly the first half of the cap, then exactly the last half: the tail is trimmed
        # byte for byte, never by whole read chunks, so the kept output never exceeds LOG_CAP.
        for chunk in iter(lambda: proc.stdout.read(65536), b""):
            room = half - len(head)
            if room > 0:
                head.extend(chunk[:room])
                chunk = chunk[room:]
            if chunk:
                tail.extend(chunk)
                if len(tail) > half:
                    excess = len(tail) - half
                    dropped[0] += excess
                    del tail[:excess]
    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    if stdin is not None:
        try:
            proc.stdin.write(stdin)
        except BrokenPipeError:
            pass
        proc.stdin.close()
    timed_out = False
    try:
        proc.wait(timeout=timeout)
    except KeyboardInterrupt:
        # Ctrl-C reaches only bug-age (the step has its own session): stop the step before going.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        proc.wait()
        if on_timeout is not None:
            on_timeout()
        raise
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        proc.wait()
        if on_timeout is not None:
            on_timeout()
    reader.join(timeout=10)
    if not reader.is_alive():
        proc.stdout.close()
    seconds = round1(time.monotonic() - t0)
    log = Path(log)
    log.parent.mkdir(parents=True, exist_ok=True)
    note = f"\n[bug-age: {dropped[0]} bytes of output not kept]\n".encode() if dropped[0] else b""
    stop = f"\n[bug-age: stopped after the {timeout} s step limit]\n".encode() if timed_out else b""
    log.write_bytes(f"$ {shlex.join(argv)}\n".encode() + bytes(head) + note + bytes(tail) + stop)
    if timed_out:
        return TIMED_OUT, seconds
    return (proc.returncode if proc.returncode >= 0 else -1), seconds


def place_overlay(spec, root):
    """Copy the overlay into the crate under `root`, never through a symlink.

    A commit can make any directory on the way a symlink (tests -> /somewhere); following it would
    write outside the work tree. Every component from `root` down is checked, and files are opened
    with O_NOFOLLOW so the last component cannot be a link either.
    """
    for rel in spec.overlay_files:
        parts = ([] if spec.crate_path == "." else spec.crate_path.split("/")) + rel.split("/")
        here = Path(root)
        for part in parts[:-1]:
            here = here / part
            if here.is_symlink():
                raise RunnerError(f"overlay path goes through a symlink: {os.path.relpath(here, root)}")
            here.mkdir(exist_ok=True)
        target = here / parts[-1]
        if target.is_symlink():
            raise RunnerError(f"overlay file would replace a symlink: {os.path.relpath(target, root)}")
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o644)
        with os.fdopen(fd, "wb") as f:
            f.write((spec.overlay / rel).read_bytes())


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
    fetch_cmd = None                    # the host's dependencies are used as they are
    overlay_marker = "bugage_repro.rs"  # a build error naming this file means the overlay does not compile
    env_markers = ()                    # build output naming a missing dependency instead

    def __init__(self, spec):
        self.wt = spec.scratch / "local-wt"

    def stage(self, spec, sha):
        """Check `sha` out into a fresh worktree and copy the overlay into the crate."""
        git_run(spec.repo, ["worktree", "remove", "--force", str(self.wt)], check=False)
        shutil.rmtree(self.wt, ignore_errors=True)
        git(spec.repo, ["worktree", "add", "--force", "--detach", str(self.wt), sha])
        place_overlay(spec, self.wt)
        return "host"

    def exec(self, spec, cmd, network, log):
        """Run `cmd` with sh in the crate directory of the worktree."""
        # The full caller environment, as the Rust runner passed it, plus the cargo settings.
        env = dict(os.environ, CARGO_TARGET_DIR=str(spec.scratch / "local-target"), CARGO_TERM_COLOR="never")
        return run_logged(["sh", "-c", cmd], log, cwd=self.wt / spec.crate_path, env=env, timeout=spec.step_timeout)

    def fallback_toolchain(self, spec, log):
        """The host toolchain has no fallback."""
        return None

    def close(self, spec):
        """Remove the worktree this run added, so the repository keeps only the worktrees it had."""
        git_run(spec.repo, ["worktree", "remove", "--force", str(self.wt)], check=False)
        shutil.rmtree(self.wt, ignore_errors=True)


KEEP_TARGETS = 2
RESET_TRIES = 20  # attempts, 0.5 s apart, to remove a volume a just-finished container may still hold
SRC = "bugage-src"
INDEX = "bugage-index"


class DockerSource:
    """Language-neutral part of the Docker runner: the per-commit source volume and the overlay.

    A profile's runner subclasses it and adds what its language needs (toolchain, dependencies,
    step environment); every profile stages source the same way and runs steps in named containers.
    """

    name = "docker"

    def __init__(self, image, namespace=""):
        self.image, self.namespace = image, namespace

    def close(self, spec):
        """Nothing to remove: the Docker runner adds no worktree to the repository."""

    def v(self, base):
        """Volume name in this runner's namespace."""
        return f"{base}{self.namespace}"

    def docker(self, args, stdin, log):
        """Run docker with `args`, logged."""
        return run_logged(["docker", *args], log, stdin=stdin)

    def untar_into(self, volume, d, tar, log):
        """Extract a tar stream into directory `d` of a volume."""
        mount = f"{self.v(volume)}:/{volume}"
        # The directory reaches the shell as an argument ($1), never as part of the script text.
        code, _ = self.docker(["run", "-i", "--rm", "-v", mount, self.image, "sh", "-c",
                               'mkdir -p "$1" && tar -x -m --no-same-owner -C "$1"', "sh", d], tar, log)
        if code != 0:
            raise RunnerError(f"harness: untar into {volume}:{d} failed (see {log})")

    def _tar_dir(self, d):
        """A tar stream of directory `d`, without macOS extended attributes."""
        out = subprocess.run(["tar", "--no-xattrs", "-C", str(d), "-cf", "-", "."], capture_output=True,
                             env=dict(os.environ, COPYFILE_DISABLE="1"))
        return out.stdout

    def reset_volume(self, volume, log):
        """Remove a volume so the next commit starts empty; raise if it cannot be removed.

        `docker run --rm` returns before the daemon has removed the container, so a removal right
        after a step can find the volume still in use. Staging over the old contents would leave
        files the new commit deleted, so this retries for a few seconds and then refuses.
        """
        for _ in range(RESET_TRIES):
            code, _ = self.docker(["volume", "rm", "-f", self.v(volume)], None, log)
            if code == 0:
                return
            time.sleep(0.5)
        raise RunnerError(f"harness: volume {self.v(volume)} is still in use (see {log}); not staging over its old contents")

    def stage_source(self, spec, sha):
        """Fill the source volume with `sha`'s tree and the overlay; return the commit's log directory."""
        logs = spec.logs / sha[:12]
        self.reset_volume(SRC, logs / "stage-reset.log")
        archive = git_run(spec.repo, ["archive", "--format=tar", sha], check=False)
        if archive.returncode != 0:
            raise RunnerError(f"harness: git archive {sha} failed")
        self.untar_into(SRC, f"/{SRC}", archive.stdout, logs / "stage-src.log")
        # Refuse a commit whose tree puts a symlink on any overlay path before extracting into it.
        check = ('root=$1; shift; set -f; IFS=/; for rel in "$@"; do p=$root; for part in $rel; do p=$p/$part; '
                 'if [ -L "$p" ]; then echo "symlink on the overlay path: ${p#$root/}"; exit 3; fi; done; done')
        crate = "" if spec.crate_path == "." else spec.crate_path + "/"
        code, _ = self.docker(["run", "--rm", "-v", f"{self.v(SRC)}:/{SRC}", self.image, "sh", "-c", check, "sh", f"/{SRC}",
                               *(crate + rel for rel in spec.overlay_files)], None, logs / "stage-overlay-check.log")
        if code == 3:
            raise RunnerError("overlay path goes through a symlink in this commit (see stage-overlay-check.log)")
        if code != 0:
            raise RunnerError(f"harness: overlay check failed (see {logs / 'stage-overlay-check.log'})")
        self.untar_into(SRC, f"/{SRC}/{spec.crate_path}", self._tar_dir(spec.overlay), logs / "stage-overlay.log")
        return logs

    def run_step(self, spec, options, cmd, log):
        """Run `cmd` with sh in the measured path of the source volume, in a named container.

        `options` are the profile's `docker run` options (network, mounts, environment). The
        container is named so a step over its time limit can be removed: killing the docker client
        alone would leave the container running.
        """
        name = f"bugage-step-{uuid.uuid4().hex[:12]}"
        args = ["run", "--rm", "--name", name, *options, "-w", f"/{SRC}/{spec.crate_path}", self.image, "sh", "-c", cmd]
        return run_logged(["docker", *args], log, timeout=spec.step_timeout,
                          on_timeout=lambda: subprocess.run(["docker", "rm", "-f", name], capture_output=True))


class Docker(DockerSource):
    """Rust profile: date-matched toolchain, crates.io as of the commit date when there is no
    Cargo.lock, `cargo fetch` with network, then offline build and test."""

    fetch_cmd = "cargo fetch"
    overlay_marker = "bugage_repro.rs"
    env_markers = ()

    def __init__(self, image, time_travel_script=None, namespace="", bucket=0):
        super().__init__(image, namespace)
        self.time_travel_script, self.bucket = time_travel_script, bucket
        self.toolchain = self.exact_toolchain = ""
        self.recent, self.unavailable = [], []

    def target_volume(self, toolchain):
        """Build-cache volume for one toolchain."""
        return f"bugage-target{self.namespace}-{toolchain}"

    def install(self, spec, log):
        """Install the current toolchain (serialised across parallel sweeps by a lock file)."""
        cmd = (f"flock /rustup/.bug-age-install.lock rustup toolchain install {self.toolchain} "
               f"--profile minimal --no-self-update")
        code, _ = self.exec(spec, cmd, True, log)
        if code != 0:
            raise RunnerError(f"toolchain {self.toolchain} could not be installed")

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
        logs = self.stage_source(spec, sha)
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
        options = [] if network else ["--network", "none", "-e", "CARGO_NET_OFFLINE=true"]
        # Build and test run the repository's code offline; they get the shared toolchain and cargo
        # caches read-only, so that code cannot change what later commits are tested with.
        ro = "" if network else ":ro"
        options += ["-v", f"{self.v(SRC)}:/{SRC}", "-v", f"{self.v(INDEX)}:/{INDEX}",
                    "-v", f"{self.target_volume(self.toolchain)}:/target", "-v", f"bugage-rustup:/rustup{ro}",
                    "-v", f"{self.v('bugage-cargo')}:/cargo{ro}", "-e", "CARGO_TARGET_DIR=/target",
                    "-e", "CARGO_TERM_COLOR=never", "-e", f"RUSTUP_TOOLCHAIN={self.toolchain}"]
        return self.run_step(spec, options, cmd, log)


# CPython minor releases with their x.y.0 dates, from 3.8: the oldest Python uv installs into.
CPYTHON = (("3.8", "2019-10-14"), ("3.9", "2020-10-05"), ("3.10", "2021-10-04"), ("3.11", "2022-10-24"),
           ("3.12", "2023-10-02"), ("3.13", "2024-10-07"), ("3.14", "2025-10-07"))
PY_RECIPE = Path(__file__).parent / "data" / "python.Dockerfile"
VENV, UV_CACHE = "bugage-venv", "bugage-uvcache"


def _minor(version):
    """(3, 10) for "3.10"."""
    major, minor = version.split(".")
    return int(major), int(minor)


def python_for(commit_unix, requires=None):
    """Date-matched CPython: the newest minor released >= 14 days before the commit, never older
    than 3.8 (uv's floor), raised to the project's declared minimum (`requires-python >= 3.x`)."""
    day = time.strftime("%Y-%m-%d", time.gmtime(commit_unix - 14 * 86400))
    chosen = CPYTHON[0][0]
    for version, released in CPYTHON:
        if released <= day:
            chosen = version
    m = re.search(r">=\s*(3\.\d+)", requires or "")
    if m and _minor(m.group(1)) > _minor(chosen):
        known = [v for v, _ in CPYTHON if _minor(v) >= _minor(m.group(1))]
        chosen = known[0] if known else chosen
    return chosen


def requires_python(repo, sha, path):
    """The `requires-python` of the project at `sha` (pyproject.toml under `path`, else the root)."""
    import tomllib
    for obj in ([f"{sha}:{path}/pyproject.toml"] if path != "." else []) + [f"{sha}:pyproject.toml"]:
        try:
            doc = tomllib.loads(git(repo, ["show", obj]))
        except (GitError, tomllib.TOMLDecodeError):
            continue
        value = doc.get("project", {}).get("requires-python")
        if isinstance(value, str):
            return value
    return None


class PythonDocker(DockerSource):
    """Python profile: CPython matched to the commit date, dependencies installed by uv with
    --exclude-newer set to the commit time (network on), then build and test offline with the
    environment mounted read-only."""

    overlay_marker = "bugage_repro_test.py"
    env_markers = ("No module named",)

    def __init__(self, namespace="", install=".", test_deps=("pytest",)):
        super().__init__("", namespace)
        self.install_spec, self.test_deps = install, tuple(test_deps)
        self.recipe = PY_RECIPE.read_text(encoding="utf-8")
        self.recipe_sha = hashlib.sha256(self.recipe.encode()).hexdigest()
        self.images, self.python, self.fetch_cmd = {}, "", None

    def image_for(self, python, log):
        """The image for one CPython minor, built from the packaged recipe the first time."""
        tag = f"bug-age-python:{python}-{self.recipe_sha[:12]}"
        if subprocess.run(["docker", "image", "inspect", tag], capture_output=True).returncode != 0:
            code, _ = run_logged(["docker", "build", "-t", tag, "--build-arg", f"PY={python}", "-"], log,
                                 stdin=self.recipe.encode())
            if code != 0:
                raise RunnerError(f"python {python} image could not be built (see {log})")
        if tag not in self.images:
            out = subprocess.run(["docker", "image", "inspect", tag, "--format", "{{.Id}}"], capture_output=True, text=True)
            self.images[tag] = out.stdout.strip()
        return tag

    def stage(self, spec, sha):
        """Choose the Python for `sha`, stage its tree and the overlay, and reset the environment."""
        logs = spec.logs / sha[:12]
        ct = int(trim(git(spec.repo, ["show", "-s", "--format=%ct", sha])))
        self.python = python_for(ct, requires_python(spec.repo, sha, spec.crate_path))
        self.image = self.image_for(self.python, logs / "stage-image.log")
        self.stage_source(spec, sha)
        self.reset_volume(VENV, logs / "stage-venv-reset.log")
        cutoff = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ct))
        # The fetch step: a fresh environment, then the project and its test dependencies as of the commit.
        # --compile-bytecode matches pip, which compiled at install time: otherwise an old dependency's
        # compile-time warnings surface at import, and a project testing with warnings as errors fails.
        self.fetch_cmd = (f"uv venv -q --python /usr/local/bin/python /{VENV} && uv pip install -q --python /{VENV}/bin/python "
                          f"--compile-bytecode --exclude-newer {cutoff} {shlex.join([self.install_spec, *self.test_deps])}")
        return f"python{self.python}"

    def exec(self, spec, cmd, network, log):
        """Run `cmd` in the measured path; offline with the environment read-only unless `network`."""
        options = [] if network else ["--network", "none"]
        ro = "" if network else ":ro"
        options += ["-v", f"{self.v(SRC)}:/{SRC}", "-v", f"{self.v(VENV)}:/{VENV}{ro}",
                    "-e", f"PATH=/{VENV}/bin:/usr/local/bin:/usr/bin:/bin", "-e", f"VIRTUAL_ENV=/{VENV}",
                    "-e", "PYTHONDONTWRITEBYTECODE=1"]
        if network:
            options += ["-v", f"{UV_CACHE}:/root/.cache/uv"]
        return self.run_step(spec, options, cmd, log)

    def fallback_toolchain(self, spec, log):
        """No second interpreter is tried."""
        return None
