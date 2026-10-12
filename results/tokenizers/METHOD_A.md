# Method A (SZZ-style) — `tokenizers/` at `fb49a2922372`

Catalog: 717 first-parent commits scanned; 109 fixes admitted by `(?i)\b(fix(e[sd]|ing)?|bugs?|hotfix)\b`; 41 excluded by rule (lint-or-format: 26, docs: 7, build-only: 3, release: 2, typo: 2, feature-name: 1).

Introducer nominated for 93 of 109 fixes.

## Bug lifetimes (nominated introducer → fix)

| Metric | Median | p90 | Max |
|---|---|---|---|
| Calendar days | 37.3 | 462.4 | 1668.6 |
| Commits elapsed | 82 | 605 | 1160 |
| Releases that shipped the bug (`v*` tags) | 0 | 9 | 44 |

Days use committer dates, except 9 bugs whose committer dates were compressed by rebases (author dates used; flagged).

## Testable window (from BUGAGE-1)

- Window start: 2025-03-13. Bugs whose nominated introducer is in the window: **4**.
- Fixes dated in the window: 6; of these, 2 have an introducer before the window (a sweep could only give a lower bound).
- 96% of bugs with a nominee were introduced before the window; a window-only study would drop them, biasing lifetimes short.

## Flags (known SZZ limits, per bug)

| Flag | Bugs |
|---|---|
| `multiple-candidates` | 53 |
| `no-blame-lines(addition-only-or-out-of-scope)` | 16 |
| `fix-is-merge(diffed-against-first-parent)` | 10 |
| `committer-dates-compressed(use-author-days)` | 9 |

## Longest-lived bugs

| Fix | Fix date | Introducer | Days | Commits | Releases | Subject |
|---|---|---|---|---|---|---|
| `5c475db339` | 2025-06-24 | `c36ac0bfdf` (2020-11-28) | 1668.6 | 479 | 44 | 🚨 breaking: Fix training with special tokens (#1617) |
| `9b77c054ef` | 2024-10-14 | `66fef2b907` (2020-08-19) | 1516.6 | 751 | 33 | Fix off-by-one error in tokenizer::normalizer::Range::len (# |
| `4ea2f235b0` | 2024-07-15 | `10ae711258` (2020-08-04) | 1440.6 | 741 | 29 | Add bytelevel normalizer to fix decode when adding tokens to |
| `aed491df8c` | 2023-10-05 | `c36ac0bfdf` (2020-11-28) | 1040.8 | 333 | 14 | Fixing the progressbar. (#1353) |
| `cd730594e9` | 2022-03-21 | `98485e7576` (2020-02-24) | 756.0 | 977 | 2 | Fixing issue with ConvBert not being able to save because of |
| `fb837b4adb` | 2022-01-06 | `8200112e9b` (2020-02-05) | 700.9 | 1014 | 0 | Fix wordlevel encode `<unk>` (#870) |
| `f24092ac62` | 2022-02-25 | `397cc539da` (2020-06-16) | 618.9 | 579 | 1 | Trying to fix loading order of added_tokens. (#924) |
| `4122a33f09` | 2022-01-04 | `082db57c49` (2020-06-09) | 573.7 | 579 | 0 | Fixing missing `direction` in TruncationParams. (#868) |
| `1bb9884f45` | 2022-03-18 | `390ef2f9f3` (2020-10-26) | 508.1 | 286 | 2 | Fixing the vocab size of the trained Unigram model (#952) |
| `c046da7679` | 2021-05-24 | `bb8321ac0d` (2020-02-17) | 462.4 | 915 | 0 | Fix stripping strings containing Unicode characters (#707) |

## Limits

- Nominee = latest toucher of removed/changed lines (`git blame -w`), not proven introducer; BUGAGE-4 checks this behaviourally.
- Addition-only fixes have no blame lines; tests/ and benches/ are out of scope; in-file `#[cfg(test)]` modules are not excluded.
- The catalog is rule-based on subjects: mixed commits (e.g. clippy + a real fix) can be excluded.

## Inputs

- `catalog.json` sha256 `2bf58d007442c04b039cb45af986d8fedc28ec0b68ecbfa0f33bc5e05c2eeac7`
- `szz.json` sha256 `b0292ad44965c8bc7dcf64b9bdb5c32c2e7cf07c3b74182733e8fc24608a14d8`
