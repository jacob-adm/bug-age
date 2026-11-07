# Long runs go here: detached, no agent in the loop, one notification at the end.
.PHONY: sweep test bundle pipeline explorer article history-scan
sweep:
	nohup scripts/sweep-unattended.sh $(ARGS) > /dev/null 2>&1 &
	@echo "sweep started in the background; notification + <results-dir>/SUMMARY.md when done"
test:
	cargo test
bundle:
	cargo run -q -- bundle --repo work/tokenizers --results results/tokenizers --repo-url https://github.com/huggingface/tokenizers --out dist/tokenizers --out-of-scope "Bindings (Python/Node), benches|out of scope for the Rust core crate|binding behaviour"
# One target end to end from its config: make pipeline TARGET=targets/rust-sdk.toml
pipeline:
	python3 scripts/pipeline.py $(TARGET) $(ARGS)

# Explorer page for every bundled target (size gate: 8 MB)
explorer:
	cargo run -q -- explorer --page explorer/index.html --targets tokenizers=dist/tokenizers,rust-sdk=dist/rust-sdk --out dist/explorer

# Render the article from bundle references; fails on any untraced number. Figures need Chrome.
article: explorer
	python3 scripts/article.py article/ARTICLE.tmpl.md --bundle tokenizers=dist/tokenizers/bundle.json --bundle rust-sdk=dist/rust-sdk/bundle.json --out article/ARTICLE.md --trace article/TRACE.md
	node scripts/capture_figures.mjs dist/explorer/index.html article/figures

# Blameless check over every file version and commit message ever committed (run before going public)
history-scan:
	python3 scripts/history_scan.py --targets work/tokenizers,work/rust-sdk --allow scripts/history_scan.allow
