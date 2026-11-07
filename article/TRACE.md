# Number trace

Every number in ARTICLE.md, the template line it comes from, and its bundle path.

| Line | Value | Bundle path |
|---|---|---|
| 3 | 37.3 | `tokenizers:summary.method_a.calendar_days.median` |
| 3 | 1668.6 | `tokenizers:summary.method_a.calendar_days.max` |
| 3 | 44 | `tokenizers:method_a[@max=days].lifetime.releases_spanned|len` |
| 23 | 20% | `tokenizers:summary.feasibility.baseline_share|pct` |
| 23 | 90% | `tokenizers:summary.feasibility.time_travel_share|pct` |
| 27 | 717 | `tokenizers:catalog.scanned` |
| 27 | 109 | `tokenizers:summary.method_a.fixes` |
| 27 | 93 | `tokenizers:summary.method_a.with_introducer` |
| 29 | 37.3 | `tokenizers:summary.method_a.calendar_days.median` |
| 29 | 82 | `tokenizers:summary.method_a.commits_elapsed.median` |
| 30 | 462.4 | `tokenizers:summary.method_a.calendar_days.p90` |
| 31 | 🚨 breaking: Fix training with special tokens (#1617) | `tokenizers:method_a[@max=days].fix|subject` |
| 31 | 1668.6 | `tokenizers:method_a[@max=days].days` |
| 31 | 479 | `tokenizers:method_a[@max=days].lifetime.commits_elapsed` |
| 35 | 6 | `tokenizers:summary.method_b.swept` |
| 35 | Fix stripping strings containing Unicode characters (#707) | `tokenizers:method_b[verdict=located].fix|subject` |
| 35 | 462.4 | `tokenizers:method_b[verdict=located].method_a_days` |
| 35 | 278.2 | `tokenizers:method_b[verdict=located].days` |
| 37 | 4 | `tokenizers:summary.method_b.verdicts.censored-by-testability` |
| 37 | Fix off-by-one error in tokenizer::normalizer::Range::len (#1638) | `tokenizers:method_b[verdict=left-censored].fix|subject` |
| 37 | 1033.7 | `tokenizers:method_b[verdict=left-censored].days` |
| 41 | 237 | `rust-sdk:summary.method_a.fixes` |
| 41 | 546 | `rust-sdk:catalog.scanned` |
| 41 | 205 | `rust-sdk:summary.method_a.with_introducer` |
| 41 | 93.6 | `rust-sdk:summary.method_a.calendar_days.median` |
| 41 | 350.9 | `rust-sdk:summary.method_a.calendar_days.p90` |
| 41 | 11 | `rust-sdk:summary.method_a.releases_shipped_bug.median` |
| 41 | 64 | `rust-sdk:summary.method_a.releases_shipped_bug.max` |
| 41 | 95% | `rust-sdk:summary.feasibility.baseline_share|pct` |
| 58 | (coverage list) | `tokenizers:coverage[status!=COVERED]` |
| 62 | (coverage list) | `rust-sdk:coverage[status!=COVERED]` |
