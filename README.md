# bug-age

Measures how long bugs lived in a git repository, using real repository data. For each fixed bug it reports commits elapsed, calendar days, and churn between the commit that introduced it and the fix.

It uses two independent methods and compares them:

- **Method A, blame-based (SZZ-style).** Runs `git blame` on the lines a fix changed and names the commit that last touched them as the likely introducer. This is fast and needs only git, but it can be wrong. Known failure cases: ghost commits, formatting-only changes, and introducers that were not the latest toucher.
- **Method B, behavioral sweep.** Writes a deterministic regression test that fails before the fix and passes after it, then replays that test across history in a hermetic per-commit Docker environment. The result is the first failing commit, the last passing commit, and every untestable commit with a reason.

Every number comes from scripts. An LLM may suggest fix commits or draft repro tests, but it never produces a metric.

Rust/Cargo is the first supported ecosystem. The first showcase target is the Rust core crate of [huggingface/tokenizers](https://github.com/huggingface/tokenizers).

## Results so far (tokenizers)

The six repros and their per-bug comparison are in [`results/tokenizers/AB.md`](results/tokenizers/AB.md). Method A's output alone is in [`results/tokenizers/METHOD_A.md`](results/tokenizers/METHOD_A.md). The feasibility spike, which covers toolchain and dependency drift across history, is in `spike/results/`.

Verdicts are honest about what could not be tested:

| Verdict | Meaning |
|---|---|
| `located` | The exact first failing commit was found |
| `censored-by-testability` | The bug is present at the first commit where the test compiles, so its age is a lower bound (`≥`) |
| `left-censored` | The bug is already present at the start of the sweep range (3 years before the fix), so its age is a lower bound |

## Requirements

- Rust 1.86 or later
- Python 3 for the driver scripts
- Docker for Method B sweeps. Build the per-commit image from `spike/Dockerfile` and tag it `bug-age-spike:4`, the name the CLI uses by default; override it with `--image`.

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
```

| Command | What it does |
|---|---|
| `catalog` | Lists the fix commits that touch a crate and records why each other commit was excluded (docs, lint, release, and so on) |
| `szz` | Method A: names a likely introducing commit for each fix in the catalog |
| `sweep` | Method B: binary-searches for the first commit where the test compiles, then bisects PASS/FAIL above it. Decisive commits are re-run `--repeats` times and flagged UNSTABLE if the result changes |
| `probe` | Runs the same test at a fixed list of commits, with no search |
| `bundle` | Builds `bundle.json` (validated against [`schema/bundle.schema.json`](schema/bundle.schema.json)), `bundle.js`, and `receipt.json` (sha256 hashes and sizes) |

## Running the pipeline

Clone the target into `work/` (the directory is git-ignored), then:

```sh
cargo build
cargo run -q -- catalog --repo work/tokenizers --path tokenizers --out results/tokenizers/catalog.json
cargo run -q -- szz --repo work/tokenizers --catalog results/tokenizers/catalog.json --out results/tokenizers/szz.json

# Method B for every repro under results/tokenizers/repros/<fix>/overlay, plus the A vs B report
python3 results/run_repros.py results/tokenizers work/tokenizers tokenizers [--workers N]

make bundle    # writes dist/tokenizers/
```

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

## License

MIT OR Apache-2.0, as declared in `Cargo.toml`.
