# Pipeline: tokenizers

- subject: https://github.com/huggingface/tokenizers `tokenizers` at `fb49a29223724a96f26e061bec8ec7517aa14177`
- generated: 2026-11-07T01:52:32+00:00

| Stage | Status | Reason | Output sha256 |
|---|---|---|---|
| clone | OK | at pinned head fb49a29223 |  |
| feasibility (baseline) | REUSED | existing report (pass --fresh to rerun) | 47dc10dc1a51f182 |
| feasibility (time-travel) | REUSED | existing report (pass --fresh to rerun) | 6e6fa99e9264e8b9 |
| catalog (rule-based fixes) | OK | catalog: 109 fixes, 41 excluded, 717 commits scanned | 2bf58d007442c04b |
| Method A (szz) | OK | szz: 109 fixes, 93 with a nominated introducer, 4 in window | b0292ad44965c8bc |
| Method B (repro sweeps) | REUSED | 6 existing sweeps (pass --fresh to rerun) |  |
| bundle | OK | bundle: 199338 bytes, sha256 1378ff43db76b5ceeb332e0fa9ef817ed32b1862ce351719c386ce2ab8bb8464, blameless gate PASS | 1378ff43db76b5ce |
