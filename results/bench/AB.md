# Method A vs Method B — per-bug lifetimes

A = SZZ nominee (latest toucher of the lines the fix changed). B = first commit where the regression test fails, found by `bug-age sweep` (date-matched toolchain, time-travel dependencies, `--network none`, 3 repeats; range = 3 years before the fix).

B days marked ≥ are lower bounds (censored). A-check probes A's nominee and its parent with the same test; it is reported separately and never changes B's verdict.

| Fix | A: nominated introducer | B: first failing commit | B verdict | A vs B | A days | B days | A-check | Commits tested / in range |
|---|---|---|---|---|---|---|---|---|
| `8a6a8dc9d5` | `e4aea890d5` (2023-03-24) | `e4aea890d5` (2023-03-24) — first commit where the test compiles | censored-by-testability | agree | 0.0 | ≥ 0.0 | not run | 13/731 |
| `9a93c50c25` | `c2664ae13f` (2023-07-28) | `c2664ae13f` (2023-07-28) — first commit where the test compiles | censored-by-testability | agree | 17.3 | ≥ 17.3 | not run | 15/593 |
| `9b77c054ef` | `66fef2b907` (2020-08-19) | `c1100ec542` (2021-12-15) — present at range start | left-censored | consistent: A predates the window | 1516.6 | ≥ 1033.7 | not run | 5/274 |
| `a350ec3e72` | `dad70e8e85` (2020-08-03) | `0a930ef1d8` (2020-09-23) — first commit where the test compiles | censored-by-testability | consistent: A predates B's earliest testable FAIL | 183.9 | ≥ 132.9 | not run | 14/928 |
| `c046da7679` | `bb8321ac0d` (2020-02-17) | `66fef2b907` (2020-08-19) | located | B later by 527 commits | 462.4 | 278.2 | A refuted by B's sweep: test PASSes at `5d8728a26b`, after the nominee | 23/960 |
| `fb837b4adb` | `8200112e9b` (2020-02-05) | `991128f9e1` (2020-10-30) — first commit where the test compiles | censored-by-testability | consistent: A predates B's earliest testable FAIL | 700.9 | ≥ 432.9 | not run | 14/1008 |

## Inputs

- `repros/8a6a8dc9d5/sweep.json` sha256 `ccf85f6ee73930ba3880a647650cb9afe16f1d49e2c1f8898b3f5fb0f493744f`
- `repros/9a93c50c25/sweep.json` sha256 `f28428bd43de65a557eed94d841caa64deb79f3219f28b5adf454b5d3bfa1738`
- `repros/9b77c054ef/sweep.json` sha256 `e06d5b742bfd2c155ed95ce8115f691eadacb42391fbe5ba8e00f07900b7dc2b`
- `repros/a350ec3e72/sweep.json` sha256 `2cf64a364f3efa15c804407fecdb8f1bd60d3df10bb728f16d259d74afeac489`
- `repros/c046da7679/sweep.json` sha256 `28f54ca9fa2af2c9ef22af1dc249afb0681f78f512f5b6a9fe0dc756665ef677`
- `repros/fb837b4adb/sweep.json` sha256 `be17c749c3bf4f256aea2178c18bfc3fb80c3ee4f99c27cc3bd90dadd8e35609`
