# Commands

Every bug-age command, the pipeline that runs them for one target, and unattended sweeps.

## Command reference

Every command accepts only its own options: an unknown, repeated or valueless option exits 2 with the usage text, and `--repeats` must be at least 1.

| Command | What it does |
|---|---|
| `catalog` | Lists the fix commits that touch a path and records why each other commit was excluded (docs, lint, release, and so on). `--profile python` adds Python lint-tool exclusions and makes Method A blame `.py` files |
| `szz` | Method A: names a likely introducing commit for each fix in the catalog |
| `sweep` | Method B: binary-searches for the first commit where the test compiles, then bisects PASS/FAIL above it. Decisive commits are re-run `--repeats` times and flagged UNSTABLE if the result changes. Bisection tests a sample, so its result is a `boundary`, a lower bound: an earlier failure is not ruled out. `--search exhaustive` tests every commit in the range, assumes nothing about commits it could not test, and is the only way to get `located` |
| `probe` | Runs the same test at a fixed list of commits, with no search |
| `bundle` | Builds `bundle.json` (validated against [`bug_age/data/bundle.schema.json`](../bug_age/data/bundle.schema.json)), `bundle.js`, and `receipt.json` (sha256 hashes and sizes) |
| `explorer` | Builds an explorer: a static viewer page for the listed bundles, with one data file per repository; fails over 8 MB. It reads reports and adds no results. |
| `mcp` | Read-only MCP server on stdio answering bundle queries; see [`dist/agent/AGENTS.md`](../dist/agent/AGENTS.md) |
| `pipeline` | Runs every stage for one target config; paths in the config are relative to the current directory |
| `dockerfile` | Prints the Dockerfile of the Method B image |

## Pipeline reference

Each target repository has one config file in [`targets/`](../targets/), and nothing else is target-specific:

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
bug-age pipeline targets/rust-sdk.toml            # or, in a clone: make pipeline TARGET=targets/rust-sdk.toml
```

An existing feasibility report is reused only if every material input recorded in its receipt matches this run: repository, pinned head, sample count, time-travel or not, package scope and the Method B image recipe, and the report still has the hash its receipt recorded. An existing sweep is reused only if its regression test is unchanged, its fix is in the pinned history, its build and test commands, repeats, runner, search and range start are what this run would use, and the file still has its recorded hash. Anything else stops the stage as stale and names the differing input (`--fresh` reruns it). Receipts made before 2.1.1 do not record the image recipe; they are reused, and the stage report says so. The bundle reads only the outputs this run produced or verified, so a skipped or stale stage adds no data.

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
