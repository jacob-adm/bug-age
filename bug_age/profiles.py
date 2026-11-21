# SPDX-License-Identifier: MIT OR Apache-2.0
"""Ecosystem profiles: what counts as source code, and which fix subjects are tooling chores.

A profile names the language of the measured path. Method A uses it to choose the files it blames;
the catalog uses it to add lint and formatter names to the exclusion rules. `rust` is the default
and is exactly the behaviour of every earlier version, so Rust results never change.
"""

NAMES = ("rust", "python")


def check(name):
    """`name` if it is a known profile, else ValueError naming the choices."""
    if name not in NAMES:
        raise ValueError(f"unknown profile {name!r} (choose from {', '.join(NAMES)})")
    return name


def _under(file, path):
    """Whether `file` lies under `path` ("." is the whole repository)."""
    return path == "." or file.startswith(path.rstrip("/") + "/")


def _rust_source(file, path):
    """Rust sources under `path`, outside tests/ and benches/ (unchanged since 1.0)."""
    return _under(file, path) and file.endswith(".rs") and "/tests/" not in file and "/benches/" not in file


def _python_source(file, path):
    """Python sources under `path`, outside test directories and test modules."""
    if not (_under(file, path) and file.endswith(".py")):
        return False
    *dirs, name = file.split("/")
    if any(d in ("tests", "test") for d in dirs):
        return False
    return not (name.startswith("test_") or name.endswith("_test.py") or name == "conftest.py")


_SOURCE = {"rust": _rust_source, "python": _python_source}

# Whether Method A ignores whitespace-only changes (git diff and git blame -w). In Python,
# indentation is code: a fix or a bug can be an indentation change and nothing else.
IGNORE_WHITESPACE = {"rust": True, "python": False}


def whitespace_flags(profile):
    """The git diff and git blame options for whitespace under `profile`: ["-w"] or []."""
    return ["-w"] if IGNORE_WHITESPACE[profile] else []

# Extra (rule name, pattern) exclusions per profile, tried after the shared rules. Tool names only:
# a bare "style" would also drop real fixes such as "Fixed missing closing </style> tag".
EXTRA_EXCLUDE = {
    "rust": (),
    "python": (("lint-tool", r"(?i)\b(mypy|flake8|pylint|ruff|isort|pep ?8)\b"),),
}


def in_scope(profile, file, path):
    """Whether Method A blames `file` for a measured `path` under `profile`."""
    return _SOURCE[profile](file, path)


def target(config):
    """Normalise a target config in place: `path` (or its older name `crate_path`) and `profile`.

    Both path keys may be given only if they agree. Afterwards `crate_path` holds the path, so
    readers written before profiles keep working, and `profile` defaults to rust.
    """
    paths = {config[k] for k in ("path", "crate_path") if k in config}
    if len(paths) != 1:
        raise ValueError("target needs path (or crate_path)" if not paths else "path and crate_path disagree")
    config["crate_path"] = paths.pop()
    config["profile"] = check(config.get("profile", "rust"))
    return config
