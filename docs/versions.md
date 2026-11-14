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
