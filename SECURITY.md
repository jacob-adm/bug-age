# Security

bug-age reads a repository's history, and Method B builds and runs that repository's code at many
past commits. Running a repository's code is the point of Method B, so the question is where that
code runs and what it can reach.

## What each part does

- **catalog, szz, bundle, explorer, mcp** run only git and read files. They never run the analysed
  repository's code.
- **Method B with `--runner local`** runs the repository's build and test commands **on your
  machine, as you**, in a git worktree under `--scratch`. It is not isolated. Use it only for
  repositories you would build yourself. The worktree is removed when the sweep or probe ends,
  including on an error or Ctrl-C, which also stops the running step.
- **Method B with `--runner docker`** (the default) runs each commit's build and test in a
  container:
  - build and test run with `--network none`;
  - the shared toolchain (`bugage-rustup`) and cargo (`bugage-cargo`) volumes are mounted
    **read-only** for build and test, so the code under test cannot change what later commits are
    tested with; only dependency fetch and toolchain install write to them;
  - the per-toolchain build cache (`bugage-target-*`) and the source volume are writable;
  - containers run as the image's default user (root inside the container). Docker isolation is a
    convenience boundary, not a sandbox for hostile code: run sweeps of untrusted repositories on a
    disposable Docker host.

## Hardening that applies to every run

- The crate path and every overlay path must be relative paths of plain characters without `..`;
  anything else is refused before any work.
- The overlay is never written through a symlink: a commit whose tree puts a symlink on an overlay
  path is reported UNTESTABLE.
- Paths reach shell commands only as arguments, never as script text.
- Every fetch, build and test step has a time limit (`--step-timeout`, default 3600 s); a step over
  it is stopped with its whole process group, or its container is removed.
- Each step's log keeps at most 8 MiB (the first and last halves), noting what was dropped.
- Bundles are checked against their schema and a blameless gate before anything is written.

## Reporting a vulnerability

Open a GitHub security advisory on this repository (Security → Report a vulnerability), or an issue
without exploit details asking for a private contact.
