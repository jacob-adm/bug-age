# Long runs go here: detached, no agent in the loop, one notification at the end.
.PHONY: sweep test bundle pipeline
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
