# Example runs

The two published runs: what they contain and how to read their Method B verdicts.

## Example runs: tokenizers and rust-sdk

The same pipeline was run on two Rust codebases. The first, the core crate of [huggingface/tokenizers](https://github.com/huggingface/tokenizers), got every stage, including Method B sweeps for six bugs. The second, the `rmcp` crate of [modelcontextprotocol/rust-sdk](https://github.com/modelcontextprotocol/rust-sdk), was added with a config file alone, to show the pipeline carries over unchanged.

**[▶ Open the live example](https://claude.ai/artifact/UDw6jyeA4zMDGhnzL7Typb)**: an explorer built from these two reports and published online. Switch between the two repositories at the top. It is a snapshot of the committed bundles and changes only when it is rebuilt and republished. Each number opens to its evidence: the SHAs, the test runs, the receipt hash and the command that reproduces it. The page also recomputes its headline numbers in your browser and flags any mismatch.

[![The bug-age explorer: headline bug ages, self-check and stage coverage for tokenizers. Click to open.](../article/figures/overview-tokenizers.png)](https://claude.ai/artifact/UDw6jyeA4zMDGhnzL7Typb)

| | tokenizers | rust-sdk |
|---|---|---|
| Config | [`targets/tokenizers.toml`](../targets/tokenizers.toml) | [`targets/rust-sdk.toml`](../targets/rust-sdk.toml) |
| Method A (every catalogued fix) | [`results/tokenizers/METHOD_A.md`](../results/tokenizers/METHOD_A.md) | [`results/rust-sdk/szz.json`](../results/rust-sdk/szz.json) |
| Method B (behavioural sweeps) | Six bugs: [`results/tokenizers/AB.md`](../results/tokenizers/AB.md) | NOT TESTED: no regression tests written yet |
| Stage report | [`results/tokenizers/PIPELINE.md`](../results/tokenizers/PIPELINE.md) | [`results/rust-sdk/PIPELINE.md`](../results/rust-sdk/PIPELINE.md) |
| Report of record (bundle) | [`dist/tokenizers/bundle.json`](../dist/tokenizers/bundle.json) | [`dist/rust-sdk/bundle.json`](../dist/rust-sdk/bundle.json) |

### What the explorer shows

These screenshots are captured by `make article` from the explorer built for the two example runs, so they always match the committed bundles.

**Lifespans.** Each bar runs from the nominated introducing commit to the fix. A date scrubber shows which bugs were alive on any day.

![Lifespan of every traced tokenizers bug](../article/figures/timeline-tokenizers.png)

**Commit × test results.** Every commit the pipeline built and tested in Docker without network: green passes, red fails, grey does not build there. Each square opens the run log.

![Commit-by-test results for tokenizers feasibility runs and regression sweeps](../article/figures/heatmap-tokenizers.png)

### Reading Method B verdicts

Verdicts are honest about what could not be tested:

| Verdict | Meaning |
|---|---|
| `located` | The exact first failing commit was found |
| `censored-by-testability` | The bug is present at the first commit where the test compiles, so its age is a lower bound (`≥`) |
| `left-censored` | The bug is already present at the start of the sweep range (3 years before the fix), so its age is a lower bound |

The feasibility check, which measures toolchain and dependency drift across history, is in `spike/results/` for tokenizers and `results/rust-sdk/spike/` for rust-sdk.
