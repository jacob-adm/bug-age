# Pipeline: rust-sdk

- subject: https://github.com/modelcontextprotocol/rust-sdk `crates/rmcp` at `5596a8a0bba2a1ec5519cc855cdadf23e4dcecdc`
- generated: 2026-11-07T02:42:43+00:00

| Stage | Status | Reason | Output sha256 |
|---|---|---|---|
| clone | OK | at pinned head 5596a8a0bb |  |
| feasibility (baseline) | OK | GO, built+tested share 0.95 | 4bdf0c7ade866a75 |
| feasibility (time-travel) | OK | NO-GO, built+tested share 0.45 | d0d17d2a86aade97 |
| catalog (rule-based fixes) | OK | catalog: 237 fixes, 28 excluded, 546 commits scanned | 331992cd3403aa5b |
| Method A (szz) | OK | szz: 237 fixes, 205 with a nominated introducer, 0 in window | 7ba3cfd0b1d54949 |
| Method B (repro sweeps) | NOT TESTED | no regression tests written for this target (results_dir/repros/<fix>/overlay) |  |
| bundle | OK | bundle: 200565 bytes, sha256 97e22ab5241d6f1df6a4524b11a731e5b1cd88eb54c971a7795912d1b665e703, blameless gate PASS | 97e22ab5241d6f1d |
