# bug-age developer targets.
#
#   make test          run the full test suite (same as CI)
#   make pipeline      run one target end to end:  make pipeline TARGET=targets/rust-sdk.toml
#   make bundle        rebuild the tokenizers bundle from its committed results
#   make explorer      rebuild the explorer page for every bundled target
#   make article       render the article and recapture its figures (needs Chrome)
#   make history-scan  blameless check over all git history (run before publishing)
#   make timings       regenerate results/TIMINGS.md and the README timing table from run records
#   make sweep         long Method B sweeps, detached:  make sweep ARGS="results/bench work/tokenizers tokenizers"

.PHONY: sweep test bundle pipeline explorer article history-scan timings

# Long runs go here: detached, no agent in the loop, one notification at the end.
sweep:
	nohup scripts/sweep-unattended.sh $(ARGS) > /dev/null 2>&1 &
	@echo "sweep started in the background; notification + <results-dir>/SUMMARY.md when done"

# Full test suite: unit, contract, oracle and end-to-end tests (the Docker test is opt-in: BUG_AGE_DOCKER_TESTS=1).
test:
	python3 -m unittest discover -s tests

# Tokenizers bundle from results/tokenizers; rust-sdk is built by `make pipeline`.
bundle:
	python3 -m bug_age bundle --repo work/tokenizers --results results/tokenizers --repo-url https://github.com/huggingface/tokenizers --out dist/tokenizers --out-of-scope "Bindings (Python/Node), benches|out of scope for the Rust core crate|binding behaviour"

# One target end to end from its config: clone, feasibility, catalog, Method A, Method B, bundle.
pipeline:
	python3 -m bug_age pipeline $(TARGET) $(ARGS)

# Explorer page for every bundled target (size gate: 8 MB).
explorer:
	python3 -m bug_age explorer --page explorer/index.html --targets tokenizers=dist/tokenizers,rust-sdk=dist/rust-sdk --out dist/explorer

# Render the article from bundle references; fails on any untraced number. Figures need Chrome.
article: explorer
	python3 scripts/article.py article/ARTICLE.tmpl.md --bundle tokenizers=dist/tokenizers/bundle.json --bundle rust-sdk=dist/rust-sdk/bundle.json --out article/ARTICLE.md --trace article/TRACE.md
	node scripts/capture_figures.mjs dist/explorer/index.html article/figures

# Blameless check over every file version and commit message ever committed (needs the target clones in work/).
history-scan:
	python3 scripts/history_scan.py --targets work/tokenizers,work/rust-sdk --allow scripts/history_scan.allow

# Timing tables from committed run records (pipeline.json, feasibility reports, sweeps, SUMMARY.md).
timings:
	python3 scripts/timings.py
