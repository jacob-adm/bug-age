# Versions

What each version of bug-age is and how to get it.

## Versions

1.0.2 is the last version written in Rust. It measures Rust crates: Method A needs git and a
Rust 1.86 toolchain to build the CLI (`cargo build`), and Method B needs Docker. It is the version
that produced the tokenizers and rust-sdk example runs. To use it, check out its tag:

```sh
git clone --branch v1.0.2 https://github.com/jacob-adm/bug-age
```

2.0.0 and later are a Python port of the same tool, installed with `pip install bug-age`. On both
example runs it reproduces every output of 1.0.2 byte for byte; the only difference in a bundle is
the `generator` string that names the version.

2.1.0 fixes an independent audit's findings. Method B no longer calls a bisected result exact: it
is a `boundary` (a lower bound), and only `--search exhaustive` reports `located`; the published
tokenizers sweep that said `located` now says `boundary`, with the same numbers (schema 1.2.0).
It also supports SHA-256 repositories, rejects unknown options (exit 2), binds reused pipeline
outputs to their inputs, stages overlays without following symlinks, mounts the shared caches
read-only for test code, bounds every step in time and log size, and always finishes redaction.

2.1.1 fixes a follow-up audit's findings. `--search exhaustive` now tests every commit in the range
instead of bisecting to the first testable one, and reports `located` only when every earlier commit
was tested and passed; an untested or flaky earlier commit makes it a `boundary`. The pipeline
reuses a stored feasibility report or sweep only when every recorded input matches what it would run
(samples, time-travel, package scope, build, test, repeats, search, start, overlay, Docker recipe
and the output's hash); measurements made before 2.1.1 do not record the Docker recipe, and reusing
one says so. Step logs keep at most exactly 8 MiB of output. Bisection results and the example runs'
numbers are unchanged.

2.2.0 measures Python projects as well as Rust crates. A target config chooses its language with
`profile = "python"` (the default, `rust`, behaves exactly as before). For Python, Method A blames
`.py` files outside the tests, and Method B and the feasibility check install the project with uv
in Docker, using the CPython release current at each commit's date and, with time-travel, only
packages published by then; tests run without network. Example runs on psf/requests and
pallets/flask are in `results/`. A source volume that Docker had not yet released could be reused
with the previous commit's files; staging now waits for it or marks the commit untestable. The
Rust example runs' numbers are unchanged.

2.2.1 keeps whitespace changes in Method A for Python. Under the python profile, `git diff` and
`git blame` no longer run with `-w`, because indentation is code in Python: a bug that is only an
indentation change, or its fix, was missed. On a published oracle of developer-confirmed
bug-introducing commits (83 Python fixes), the true introducer is now named for 58 fixes instead
of 55. The Python example runs were regenerated: on psf/requests 9 of 169 primary nominees changed
and one more fix has a nominee; on pallets/flask 6 of 185 changed and two more have one. The one
regression test whose nominee changed was probed again (A-check). Rust is unchanged.
