# Method

How bugs are found, which steps are deterministic and where AI was used, and the rules every result follows.

## How bugs are found

bug-age does not discover new bugs. It works from bugs the project has already fixed, and uses testing only to date some of them.

1. **Find the fixes (no testing).** Read the first-parent commit history of the crate and keep commits whose subject says `fix`, `bug` or `hotfix`. Fixed rules exclude typo, docs, lint, CI, release and similar commits. Each remaining commit counts as one bug. Every decision is recorded with the rule that made it.
2. **Date every fix from history (Method A, no testing).** Blame the lines each fix changed; the commit that last touched them is the nominated introducer. Age is the time, commits and releases between that commit and the fix.
3. **Date selected bugs by testing (Method B).** For a few bugs, a regression test reproduces the bug. It must fail just before the fix and pass at the fix, or it is rejected. The test is then run on older commits, in Docker without network, to find where the failure first appears.

What this means for the numbers:

- Bugs that were never fixed, or were fixed in a commit whose subject does not say so, are not counted.
- A commit that says "fix" but is not a bug fix is counted unless an exclusion rule catches it. This is one reason Method A is reported as PARTIAL.
- Method A covers every catalogued fix but is a nomination. Method B is evidence, but only for the bugs that have a regression test.

## What is deterministic and what uses AI

**Deterministic.** These parts make no model calls. Given the same repository, pinned commit and config, they produce the same output, and `make pipeline` needs no API key.

| Part | How it works |
|---|---|
| Fix catalog | Regular-expression rules over commit subjects, plus exclusion rules (docs, lint, release, ...). The `python` profile adds lint-tool names (mypy, flake8, pylint, ruff, isort, pep8). Locked by `classify_rules`. |
| Method A | `git blame` on the lines each fix changed, in the profile's source files only (`rust`: `.rs` outside `tests/` and `benches/`; `python`: `.py` outside test directories, `test_*.py`, `*_test.py` and `conftest.py`). Under `rust`, `git diff` and `git blame` run with `-w`, so whitespace-only changes are ignored; under `python` they are kept, as indentation is code. Days, commits, releases and churn computed from git. |
| Buildability and Method B sweeps | Each commit built and tested in Docker with no network and a date-matched toolchain. PASS or FAIL comes from the test's exit status, and decisive commits are re-run. `rust`: Rust toolchain by date, crates.io as of the commit date for commits without `Cargo.lock`. `python`: the newest CPython released at least 14 days before the commit (never older than 3.8, raised to `requires-python`), and every dependency installed by uv as published by the commit time (`--exclude-newer`); the environment is read-only while tests run. Commits uv cannot install (typically before 2019) are UNTESTABLE with the reason. |
| Bundle and summary | Medians, 90th percentiles, counts and coverage computed by the CLI; the blameless gate rejects names and emails. |
| Explorer (viewer) | Displays the bundles it was built from as they are, recomputes the headline numbers in the browser, and ranks search results with fixed rules. |
| MCP server | Returns values copied from the bundle; unknown input is an error, never a guess. |
| Article numbers | Inserted from the bundle by `scripts/article.py`, which fails on any number typed into the prose. |
| History scan | Fixed identity and email patterns over every committed file and message. |

**Uses AI.** In each case the AI's output is checked mechanically, and none of it becomes a number.

| Part | What AI did | What checks it |
|---|---|---|
| Method B regression tests (`results/<target>/repros/*/overlay`) | Drafted by an AI coding agent from each fix's diff | The sweep counts a test only if it fails before the fix and passes after it; otherwise the verdict is `repro-invalid`. Whether a test captures the real bug is a human judgement, so read the overlay. |
| Article prose (`article/ARTICLE.tmpl.md`) | Drafted with AI | Every number is a bundle reference; the check fails on anything else. |
| "Ask Claude" in the explorer (optional) | Claude answers a question on the viewer's own account, from the rows the search found | The answer is shown only if every cited SHA and every number appears in those rows. It runs only when the viewer clicks, and is hidden where unavailable. |
| The code | Written with an AI coding agent (Claude Code) and reviewed by the maintainer | Each change merged through a pull request after `cargo test`; commits carry a `Co-Authored-By` line. |

## Rigor rules

- The subject is pinned: repo URL, SHA range, toolchain, and tool versions.
- Sweeps run with `--network none`, a date-matched toolchain, and dependencies resolved as they were at that date.
- A result is PASS only when its assertions actually ran. Anything else is reported as NOT TESTED.
- The bundle is blameless. It contains SHAs, dates, and short commit subjects only. Author names, emails, and usernames are redacted, and a gate fails the build if any remain.
