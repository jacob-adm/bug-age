# Long runs go here: detached, no agent in the loop, one notification at the end.
.PHONY: sweep test bundle
sweep:
	nohup scripts/sweep-unattended.sh $(ARGS) > /dev/null 2>&1 &
	@echo "sweep started in the background; notification + <results-dir>/SUMMARY.md when done"
test:
	cargo test
bundle:
	cargo run -q -- bundle --repo work/tokenizers --results results/tokenizers --repo-url https://github.com/huggingface/tokenizers --out dist/tokenizers
