# Method A vs Method B — per-bug lifetimes

A = SZZ nominee (latest toucher of the lines the fix changed). B = first commit where the regression test fails, found by `bug-age sweep` (date-matched toolchain, time-travel dependencies, `--network none`, 3 repeats; range = 3 years before the fix).

B days marked ≥ are lower bounds (censored). A-check probes A's nominee and its parent with the same test; it is reported separately and never changes B's verdict.

| Fix | A: nominated introducer | B: first failing commit | B verdict | A vs B | A days | B days | A-check | Commits tested / in range |
|---|---|---|---|---|---|---|---|---|
| `47914226c2` | `171b370b0e` (2012-03-31) | `cb7fcd7ebd` (2023-08-12) — first commit where the test compiles | censored-by-testability | consistent: A predates B's earliest testable FAIL | 5066.8 | ≥ 915.3 | A untested: test cannot compile at the nominee or its parent | 12/144 |
| `bc7dd0fc4d` | `e36f34597c` (2022-06-08) | `9439fad038` (2024-02-20) — first commit where the test compiles | censored-by-testability | consistent: A predates B's earliest testable FAIL | 1390.9 | ≥ 768.7 | A untested: test cannot compile at the nominee or its parent | 11/163 |
| `f0198e6dfc` | `cb0914407b` (2018-01-04) | `9439fad038` (2024-02-20) — first commit where the test compiles | censored-by-testability | consistent: A predates B's earliest testable FAIL | 3007.0 | ≥ 768.7 | A untested: test cannot compile at the nominee or its parent | 11/164 |

## Inputs

- `repros/47914226c2/sweep.json` sha256 `511dc6ed015c9616cce5023251930b07f2c42a36e0bf9fda1c5ef1140b99159d`
- `repros/bc7dd0fc4d/sweep.json` sha256 `cb2cfe23140e8e4ad5be24d2e5cf2f845c2f2de9fda732fb837486345dcae5a5`
- `repros/f0198e6dfc/sweep.json` sha256 `8a2652261a7040747a764cdbe1a6aa45c5278a97671d32b0fe4e4433d5a8fc77`
