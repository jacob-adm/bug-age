# BUGAGE-1 feasibility spike — verdict: **NO-GO**

Subject: `https://github.com/huggingface/tokenizers.git` crate path `tokenizers/` at HEAD `fb49a29223724a96f26e061bec8ec7517aa14177` (717 first-parent commits touch the crate; sampled window 2019-11-01 → 2026-10-07).

Decision rule (fixed before the run): GO iff BUILT_AND_TESTED share >= 70% and no FLAKY. Result: 20.0% BUILT_AND_TESTED.

| Status | Commits |
|---|---|
| BUILD_FAILED | 2 |
| BUILT_AND_TESTED | 4 |
| NOT_TESTED | 14 |

## Method

- **build**: cargo build --all --offline in docker --network none
- **decision_rule**: GO iff BUILT_AND_TESTED share >= 70% and no FLAKY
- **not_covered**: integration tests under tests/ (need downloaded fixtures), benches, bindings
- **sampling**: 20 evenly spaced first-parent commits touching tokenizers/
- **test**: cargo test --all --lib --offline (all workspace members' unit tests) in docker --network none, repeated 2x
- **toolchain_rule**: latest stable released >=14 days before commit date, raised to rust-version; aarch64-unknown-linux-gnu in bug-age-spike:2

## Per-commit results

| # | SHA | Date | Toolchain | Edition | Lockfile | Status | Reason |
|---|---|---|---|---|---|---|---|
| 0 | `2b72a5737f` | 2019-11-01 | 1.38 | 2018 | yes | NOT_TESTED | build ok but zero unit tests executed |
| 38 | `4807894da6` | 2019-12-11 | 1.39 | 2018 | yes | BUILD_FAILED | compile error |
| 75 | `c0ed873c4d` | 2019-12-23 | 1.39 | 2018 | yes | BUILT_AND_TESTED | 13 unit tests passed x2 |
| 113 | `805dc58949` | 2020-01-03 | 1.40 | 2018 | no | NOT_TESTED | dependency fetch/resolution failed: edition newer than toolchain |
| 151 | `6524f09e99` | 2020-02-03 | 1.40 | 2018 | no | NOT_TESTED | dependency fetch/resolution failed: edition newer than toolchain |
| 188 | `6c232886b8` | 2020-03-26 | 1.41 | 2018 | no | NOT_TESTED | dependency fetch/resolution failed: edition newer than toolchain |
| 226 | `bb68ec3414` | 2020-06-11 | 1.43 | 2018 | no | NOT_TESTED | dependency fetch/resolution failed: edition newer than toolchain |
| 264 | `fcc68f27f6` | 2020-08-03 | 1.45 | 2018 | no | NOT_TESTED | dependency fetch/resolution failed: edition newer than toolchain |
| 301 | `857948e5b8` | 2020-08-31 | 1.45 | 2018 | no | NOT_TESTED | dependency fetch/resolution failed: edition newer than toolchain |
| 339 | `481f3bd976` | 2020-09-02 | 1.45 | 2018 | no | NOT_TESTED | dependency fetch/resolution failed: edition newer than toolchain |
| 377 | `98a30eead1` | 2020-09-24 | 1.46 | 2018 | no | NOT_TESTED | dependency fetch/resolution failed: edition newer than toolchain |
| 415 | `d3d9f2c76b` | 2020-11-09 | 1.47 | 2018 | no | NOT_TESTED | dependency fetch/resolution failed: edition newer than toolchain |
| 452 | `2e2e7558f7` | 2021-05-20 | 1.51 | 2018 | no | BUILD_FAILED | edition newer than toolchain |
| 490 | `a4a68de98a` | 2022-02-28 | 1.58 | 2018 | no | NOT_TESTED | dependency fetch/resolution failed: edition newer than toolchain |
| 528 | `33a57e6418` | 2023-01-18 | 1.66 | 2018 | no | NOT_TESTED | dependency fetch/resolution failed: edition newer than toolchain |
| 565 | `aed491df8c` | 2023-10-05 | 1.72 | 2018 | no | NOT_TESTED | dependency fetch/resolution failed: edition newer than toolchain |
| 603 | `adc82cb49a` | 2024-08-06 | 1.79 | 2018 | no | NOT_TESTED | dependency fetch/resolution failed: edition newer than toolchain |
| 641 | `4383a25787` | 2025-03-13 | 1.85 | 2018 | no | BUILT_AND_TESTED | 189 unit tests passed x2 |
| 678 | `c58a47475c` | 2026-02-24 | 1.93 | 2018 | no | BUILT_AND_TESTED | 192 unit tests passed x2 |
| 716 | `ff8ae1baab` | 2026-10-07 | 1.98 | 2024 | yes | BUILT_AND_TESTED | 281 unit tests passed x2 |

## Testable window today

Newest unbroken run of BUILT_AND_TESTED samples: 3 of 20, from 2025-03-13 (`4383a25787`) to 2026-10-07. A behavioral sweep is feasible as-is inside this window; older commits need the mitigations below.

## Drift and environment findings

- **Dependency drift**: 16 of 20 sampled commits have no committed `Cargo.lock`; their dependencies were resolved against today's registry, not the versions used at the time.
- **Toolchain pin**: `rust-toolchain` values seen: ['None', 'stable'] (`stable` floats, so it pins nothing).
- **Fixture-dependent integration tests**: 13 of 20 sampled commits have test files reading `data/` (downloaded fixtures). These were NOT TESTED; unit tests only.
- **Fixture URLs in Makefiles** (10 distinct), HTTP status today: `https://huggingface.co/Narsil/llama-tokenizer/resolve/main/tokenizer.json` → 200, `https://huggingface.co/Narsil/small/raw/main/roberta.json` → 200, `https://huggingface.co/hf-internal-testing/llama3-tokenizer/resolve/main/tokenizer.json` → 200, `https://norvig.com/big.txt` → 200, `https://s3.amazonaws.com/models.huggingface.co/bert/albert-base-v1-tokenizer.json` → 200, `https://s3.amazonaws.com/models.huggingface.co/bert/anthony/doc-pipeline/tokenizer.json` → 200, `https://s3.amazonaws.com/models.huggingface.co/bert/anthony/doc-quicktour/tokenizer.json` → 200, `https://s3.amazonaws.com/models.huggingface.co/bert/gpt2-merges.txt` → 200, `https://s3.amazonaws.com/models.huggingface.co/bert/gpt2-vocab.json` → 200, `https://storage.googleapis.com/tokenizers/roberta.json` → 403. Not probed (Makefile patterns): `https://huggingface.co/Narsil/small/raw/main/unigram$*`, `https://s3.amazonaws.com/models.huggingface.co/bert/bert-$*`, `https://s3.amazonaws.com/models.huggingface.co/bert/gpt2-$*`, `https://storage.googleapis.com/tokenizers/unigram$*`
- **Licenses seen** (`license` key in the crate Cargo.toml; None = key absent): ['Apache-2.0', 'None']
- **Host linker drift (native macOS)**: smoke run on this Mac → `2b72a5737f` (1.38-x86_64-apple-darwin): BUILD_FAILED — linker said: `= note: ld: multiple errors: archive member 'rust.metadata.bin' not a mach-o file in '~/.r…`; `ff8ae1baab` (1.98-aarch64-apple-darwin): BUILT_AND_TESTED. Hence all build/test steps run in a Linux container (`results/smoke-native-macos.*`).
- **Harness hermeticity**: a worktree nested inside bug-age's own Cargo workspace absorbed old commits (no `[workspace]`) into the parent workspace; scratch dirs now live outside the repo.

## Mitigations to evaluate before the sweep (not run in this spike)

- Time-travel dependency resolution for lockfile-less commits: resolve each crate to the newest version published before the commit date (crates.io version timestamps). The nightly cargo used here has no built-in flag for this.
- Treat genuinely broken commits (compile errors on the commit's own code) as untestable intervals, never as bug-present.
- Fixture snapshotting: vendor the HF test fixtures at a pinned revision so integration tests can run offline.

## Evidence receipt

- Command: `python3 spike/feasibility.py --samples 20`, then `python3 spike/feasibility.py --reclassify`
- Generated: 2026-10-12T19:55:59+00:00
- Versions: {"docker": "28.3.3 arm64", "git": "git version 2.50.1 (Apple Git-155)", "host": "Darwin arm64", "image": "sha256:76a5e56ed4bb3ea0d326f0249bd816cd0fe3b7a375264249d60745de369608d6", "python": "3.14.8", "toolchains": ["1.38", "1.39", "1.40", "1.41", "1.43", "1.45", "1.46", "1.47", "1.51", "1.58", "1.66", "1.72", "1.79", "1.85", "1.93", "1.98"]}
- `report.json` sha256: `47dc10dc1a51f1820211b001a88dac5aa7d9f1dee753d7c9ab265098820f7b2a`

## What this does and does not prove

- COVERED: build + workspace unit tests at the sampled commits, offline, repeated for flakiness.
- PARTIAL: dependency versions for lockfile-less commits are today's, not historical.
- NOT TESTED: integration tests needing downloaded fixtures, benches, Python/Node bindings, commits between samples.
