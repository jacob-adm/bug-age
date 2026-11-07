# bug-age

Measures how long bugs lived in a git repository, using real repository data. For each fixed bug it reports commits elapsed, calendar days, releases shipped, and churn between the commit that introduced it and the fix.

It uses two independent methods and compares them:

- **Method A, blame-based (SZZ-style).** Runs `git blame` on the lines a fix changed and names the commit that last touched them as the likely introducer. This is fast and needs only git, but it can be wrong. Known failure cases: ghost commits, formatting-only changes, and introducers that were not the latest toucher.
- **Method B, behavioral sweep.** Takes a regression test that fails before the fix and passes after it, then replays that test across history in a hermetic per-commit Docker environment. The result is the first failing commit, the last passing commit, and every untestable commit with a reason.

Every number comes from scripts. AI helped write the code, the Method B regression tests and the article prose, but no model produces or changes a number. See [What is deterministic and what uses AI](#what-is-deterministic-and-what-uses-ai). bug-age supports Rust crates today.

What you get, and the three names this README uses for it:

- **Report.** What a run produces: the result files in `results/<name>/` and one bundle, `dist/<name>/bundle.json`, which holds every number. Each repository you run gets its own report.
- **Explorer.** A viewer. It is a static HTML page you build from one or more bundles to browse their reports. It holds no results of its own and runs no analysis.
- **Live example.** One explorer, built from the reports of the two [example runs](#example-runs-tokenizers-and-rust-sdk) and published online. It is a snapshot: running bug-age on other repositories does not change it.

To see the output first, [open the live example](https://claude.ai/artifact/UDw6jyeA4zMDGhnzL7Typb).

## Get started

Point bug-age at your own repository in six steps. A first run with Method A only needs git and Rust; Docker is needed only for the feasibility check and Method B.

**1. Install the requirements and build.**

```sh
git clone https://github.com/jacob-adm/bug-age && cd bug-age
cargo build                                          # Rust 1.86 or later
docker build -t bug-age-spike:4 -f spike/Dockerfile spike   # only for feasibility and Method B
```

You also need git and Python 3.11 or later. The Docker image name `bug-age-spike:4` is the CLI default; pass `--image` to use another.

**2. Describe your repository in a config file.** Copy an existing one and edit it:

```sh
cp targets/rust-sdk.toml targets/myrepo.toml
```

| Key | Required | What to set |
|---|---|---|
| `name` | yes | Short name: lowercase letters, digits and `-`. Used in file names and the explorer. |
| `repo_url` | yes | Clone URL of the repository. |
| `head` | yes | Full SHA of the commit to analyse up to. Pinning it makes the run reproducible. |
| `crate_path` | yes | Directory of the crate inside the repository (`.` for the root). Only history under this path is analysed. |
| `work_dir`, `results_dir`, `spike_dir`, `dist_dir` | yes | Where the clone, results, feasibility reports and bundle go, relative to this repository. Follow the pattern `work/<name>`, `results/<name>`, `results/<name>/spike`, `dist/<name>`. |
| `release_tag_glob` | no | Pattern matching your release tags, for release counts. Default `v[0-9]*`. Set it if your tags look different, e.g. `mycrate-v[0-9]*`, or every release count will be 0. |
| `package` | no | Cargo package to build and test in a workspace. Default: the whole workspace. |
| `samples` | no | Commits sampled by the feasibility check. Default 20. |
| `szz_window_start` | no | `YYYY-MM-DD`. Flags fixes whose introducer falls on or after this date. |
| `out_of_scope` | no | `STAGE\|EVIDENCE\|DOES_NOT_PROVE`: a part of the repository you deliberately leave out, listed as NOT TESTED. |

**3. Run the pipeline.**

```sh
make pipeline TARGET=targets/myrepo.toml ARGS=--skip-feasibility   # Method A only, no Docker
make pipeline TARGET=targets/myrepo.toml                           # adds the Docker feasibility check
```

**4. Read the report.** `results/myrepo/PIPELINE.md` lists every stage with its status (OK, REUSED, FAILED or NOT TESTED), the reason, and the time taken. The bundle, `dist/myrepo/bundle.json`, is the report of record: every number for this repository is in it. Its sha256 and the exact command that built it are in `dist/myrepo/receipt.json`.

**5. Browse the report in your own explorer.** This builds a viewer for your bundle on your machine. The published live example is not affected and keeps showing only the two example runs. To browse several of your repositories together, list them all: `--targets a=dist/a,b=dist/b`.

```sh
target/debug/bug-age explorer --page explorer/index.html --targets myrepo=dist/myrepo --out dist/explorer-myrepo
open dist/explorer-myrepo/index.html        # or open the file in any browser
```

**6. Optional: date selected bugs by testing (Method B).** Pick a fix from `results/myrepo/catalog.json` and add a regression test at `results/myrepo/repros/<first 10 chars of the fix SHA>/overlay/tests/bugage_repro.rs`. The overlay is copied into the crate at every commit tested, so the test can only use the crate's public API. It must fail at the commit just before the fix and pass at the fix; otherwise the sweep rejects it as `repro-invalid`. Run step 3 again: Method B runs whenever a regression test has no sweep yet. See `results/tokenizers/repros/` for six examples.

## Example runs: tokenizers and rust-sdk

The same pipeline was run on two Rust codebases. The first, the core crate of [huggingface/tokenizers](https://github.com/huggingface/tokenizers), got every stage, including Method B sweeps for six bugs. The second, the `rmcp` crate of [modelcontextprotocol/rust-sdk](https://github.com/modelcontextprotocol/rust-sdk), was added with a config file alone, to show the pipeline carries over unchanged.

**[▶ Open the live example](https://claude.ai/artifact/UDw6jyeA4zMDGhnzL7Typb)**: an explorer built from these two reports and published online. Switch between the two repositories at the top. It is a snapshot of the committed bundles and changes only when it is rebuilt and republished. Each number opens to its evidence: the SHAs, the test runs, the receipt hash and the command that reproduces it. The page also recomputes its headline numbers in your browser and flags any mismatch.

[![The bug-age explorer: headline bug ages, self-check and stage coverage for tokenizers. Click to open.](article/figures/overview-tokenizers.png)](https://claude.ai/artifact/UDw6jyeA4zMDGhnzL7Typb)

| | tokenizers | rust-sdk |
|---|---|---|
| Config | [`targets/tokenizers.toml`](targets/tokenizers.toml) | [`targets/rust-sdk.toml`](targets/rust-sdk.toml) |
| Method A (every catalogued fix) | [`results/tokenizers/METHOD_A.md`](results/tokenizers/METHOD_A.md) | [`results/rust-sdk/szz.json`](results/rust-sdk/szz.json) |
| Method B (behavioural sweeps) | Six bugs: [`results/tokenizers/AB.md`](results/tokenizers/AB.md) | NOT TESTED: no regression tests written yet |
| Stage report | [`results/tokenizers/PIPELINE.md`](results/tokenizers/PIPELINE.md) | [`results/rust-sdk/PIPELINE.md`](results/rust-sdk/PIPELINE.md) |
| Report of record (bundle) | [`dist/tokenizers/bundle.json`](dist/tokenizers/bundle.json) | [`dist/rust-sdk/bundle.json`](dist/rust-sdk/bundle.json) |

### What the explorer shows

These screenshots are captured by `make article` from the explorer built for the two example runs, so they always match the committed bundles.

**Lifespans.** Each bar runs from the nominated introducing commit to the fix. A date scrubber shows which bugs were alive on any day.

![Lifespan of every traced tokenizers bug](article/figures/timeline-tokenizers.png)

**Commit × test results.** Every commit the pipeline built and tested in Docker without network: green passes, red fails, grey does not build there. Each square opens the run log.

![Commit-by-test results for tokenizers feasibility runs and regression sweeps](article/figures/heatmap-tokenizers.png)

### Reading Method B verdicts

Verdicts are honest about what could not be tested:

| Verdict | Meaning |
|---|---|
| `located` | The exact first failing commit was found |
| `censored-by-testability` | The bug is present at the first commit where the test compiles, so its age is a lower bound (`≥`) |
| `left-censored` | The bug is already present at the start of the sweep range (3 years before the fix), so its age is a lower bound |

The feasibility check, which measures toolchain and dependency drift across history, is in `spike/results/` for tokenizers and `results/rust-sdk/spike/` for rust-sdk.

## How bugs are found

bug-age does not discover new bugs. It works from bugs the project has already fixed, and uses testing only to date some of them.

1. **Find the fixes (no testing).** Read the first-parent commit history of the crate and keep commits whose subject says `fix`, `bug` or `hotfix`. Fixed rules exclude typo, docs, lint, CI, release and similar commits. Each remaining commit counts as one bug. Every decision is recorded with the rule that made it.
2. **Date every fix from history (Method A, no testing).** Blame the lines each fix changed; the commit that last touched them is the nominated introducer. Age is the time, commits and releases between that commit and the fix.
3. **Date selected bugs by testing (Method B).** For a few bugs, a regression test reproduces the bug. It must fail just before the fix and pass at the fix, or it is rejected. The test is then run on older commits, in Docker without network, to find where the failure first appears.

What this means for the numbers:

- Bugs that were never fixed, or were fixed in a commit whose subject does not say so, are not counted.
- A commit that says "fix" but is not a bug fix is counted unless an exclusion rule catches it. This is one reason Method A is reported as PARTIAL.
- Method A covers every catalogued fix but is a nomination. Method B is evidence, but only for the bugs that have a regression test.

## How long it takes

<!-- timings:begin -->

Measured on Darwin arm64, Docker 28.3.3 arm64. Figures come from committed run records via `scripts/timings.py`; full tables in [`results/TIMINGS.md`](results/TIMINGS.md). Step time excludes container staging and toolchain installs, so expect wall time to be longer.

| Stage | What was measured | Time |
|---|---|---|
| catalog | last pipeline run, 2 target(s) | 3-4 s |
| Method A | last pipeline run, 2 target(s) | 27-53 s |
| bundle | last pipeline run, 2 target(s) | 5-6 s |
| Feasibility (one run, 20 sampled commits) | 4 runs | 4 min to 7 min per run |
| Method B sweep (one bug, current search) | 6 sweeps, 84 commits | 101 s to 6 min of step time per bug; median per commit 7 s to 22 s |
| Method B, all 6 tokenizers sweeps end to end | one unattended run, wall clock | 20 min |

Method B dominates: each bug needs a regression test, and the current search built and tested 5 to 23 commits per bug in Docker. Catalog, Method A and bundle together took 36 to 62 s per repository.

<!-- timings:end -->

## What is deterministic and what uses AI

**Deterministic.** These parts make no model calls. Given the same repository, pinned commit and config, they produce the same output, and `make pipeline` needs no API key.

| Part | How it works |
|---|---|
| Fix catalog | Regular-expression rules over commit subjects, plus exclusion rules (docs, lint, release, ...). Locked by `classify_rules`. |
| Method A | `git blame` on the lines each fix changed; days, commits, releases and churn computed from git. |
| Buildability and Method B sweeps | Each commit built and tested in Docker with no network and a date-matched toolchain. PASS or FAIL comes from the test's exit status, and decisive commits are re-run. |
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

## CLI

```
bug-age catalog --repo DIR --path CRATE [--head REV] [--out FILE]
bug-age szz     --repo DIR --catalog FILE [--window-start YYYY-MM-DD] [--out FILE]
bug-age sweep   --repo DIR --path CRATE --fix SHA --overlay DIR --test CMD
                [--build CMD] [--start SHA] [--runner docker|local] [--repeats N] [--image IMG]
                [--time-travel-script FILE|none] [--scratch DIR] [--logs DIR] [--out FILE]
                [--namespace NAME] [--bucket N]
bug-age probe   --repo DIR --path CRATE --commits SHA,SHA,... --overlay DIR --test CMD [same options]
bug-age bundle  --repo DIR --results DIR --repo-url URL --out DIR [--spike DIR]
bug-age explorer --page FILE --targets NAME=DIR,... --out DIR
bug-age mcp     --bundles NAME=FILE,...
```

| Command | What it does |
|---|---|
| `catalog` | Lists the fix commits that touch a crate and records why each other commit was excluded (docs, lint, release, and so on) |
| `szz` | Method A: names a likely introducing commit for each fix in the catalog |
| `sweep` | Method B: binary-searches for the first commit where the test compiles, then bisects PASS/FAIL above it. Decisive commits are re-run `--repeats` times and flagged UNSTABLE if the result changes |
| `probe` | Runs the same test at a fixed list of commits, with no search |
| `bundle` | Builds `bundle.json` (validated against [`schema/bundle.schema.json`](schema/bundle.schema.json)), `bundle.js`, and `receipt.json` (sha256 hashes and sizes) |
| `explorer` | Builds an explorer: a static viewer page for the listed bundles, with one data file per repository; fails over 8 MB. It reads reports and adds no results. |
| `mcp` | Read-only MCP server on stdio answering bundle queries; see [`dist/agent/AGENTS.md`](dist/agent/AGENTS.md) |

## Pipeline reference

Each target repository has one config file in [`targets/`](targets/), and nothing else is target-specific:

```toml
name = "rust-sdk"
repo_url = "https://github.com/modelcontextprotocol/rust-sdk"
head = "5596a8a0bba2a1ec5519cc855cdadf23e4dcecdc"   # pinned subject
crate_path = "crates/rmcp"
work_dir = "work/rust-sdk"
results_dir = "results/rust-sdk"
spike_dir = "results/rust-sdk/spike"
dist_dir = "dist/rust-sdk"
samples = 20
# optional: szz_window_start = "YYYY-MM-DD", out_of_scope = "STAGE|EVIDENCE|DOES_NOT_PROVE"
```

One command runs every stage:

```sh
make pipeline TARGET=targets/rust-sdk.toml        # or: python3 scripts/pipeline.py targets/rust-sdk.toml
```

The stages are clone at the pinned head, feasibility (baseline and time-travel dependencies), catalog, Method A, Method B for every repro under `<results_dir>/repros/<fix>/overlay`, and bundle.

- A stage whose output already exists is REUSED, so the expensive Docker stages are never redone silently. Pass `--fresh` to rerun them.
- A failing stage is recorded with its reason, and the stages that don't depend on it still run.
- The run writes `<results_dir>/PIPELINE.md` and `pipeline.json`, listing each stage's status, reason, time taken and output sha256.
- A stage that did not run appears in the bundle's coverage as NOT TESTED.

Method B needs a regression test per bug, written as a test overlay. Those tests are drafted per target, so a target without any shows Method B as NOT TESTED.

### Unattended sweeps

```sh
make sweep ARGS="results/bench work/tokenizers tokenizers"
```

The sweep runs detached, with no agent involved. It writes `<results>/SUMMARY.md` and sends one macOS notification when it finishes. To check a run against committed results:

```sh
python3 results/compare_runs.py results/tokenizers results/bench   # prints IDENTICAL or the differences
```

## Rigor rules

- The subject is pinned: repo URL, SHA range, toolchain, and tool versions.
- Sweeps run with `--network none`, a date-matched toolchain, and dependencies resolved as they were at that date.
- A result is PASS only when its assertions actually ran. Anything else is reported as NOT TESTED.
- The bundle is blameless. It contains SHAs, dates, and short commit subjects only. Author names, emails, and usernames are redacted, and a gate fails the build if any remain.

## Tests

```sh
cargo test                 # unit and CLI tests
cargo test -- --ignored    # adds the end-to-end Docker runner test (needs the image)
```

## Contributing

Changes reach `main` only through pull requests.

1. Fork the repository and create a branch.
2. Make the change, then run `cargo test`. If you changed bundles, results or the article, also run `make article timings`.
3. Open a pull request against `main`. CI runs the tests and the article and timing checks on Linux and macOS; all must pass before merging. Pull requests are merged with a merge commit.

Keep the rules in [Rigor rules](#rigor-rules): numbers come from scripts, unrun stages are NOT TESTED, and bundles stay blameless.

## License

MIT OR Apache-2.0, as declared in `Cargo.toml`.
