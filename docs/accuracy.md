# Accuracy of Method A

Method A names the commit that likely introduced a bug by blaming the lines its fix changed. This
page measures how often that commit is the right one, against an oracle in which the developers
themselves named the bug-introducing commits, and puts PyDriller's SZZ on the same fixes beside it.

## Oracle and selection

- **Oracle.** Rosa et al., "Evaluating SZZ Implementations Through a Developer-informed Oracle",
  ICSE 2021. Its replication package lists fix commits with the bug-introducing commits named in
  the developers' own words. The file used is `json-input-raw/bugfix_commits_all.json` at commit
  `45a712d` of
  [grosa1/icse2021-szz-replication-package](https://github.com/grosa1/icse2021-szz-replication-package).
- **Selection.** Entries whose only language is Python: 272 fixes in 243 repositories, of which
  231 still exist on GitHub. The 80 smallest of those by GitHub's reported size are kept, to keep
  the clones small; the list is `results/oracle/repos.tsv`. They hold 84 fixes; one fix commit is
  no longer in its repository, which leaves 83.
- **bug-age.** `bug-age szz` with the `python` profile on a catalog of exactly those fixes.
- **PyDriller.** `Git.get_commits_last_modified_lines`, its B-SZZ implementation: every commit that
  last modified a line the fix deleted or changed.

## Metrics

Each fix has a set of true introducers from the oracle and a set of named commits from each tool.
Over all (fix, commit) pairs: precision is correct named commits over all named commits, recall
is correct named commits over all true introducers, and F1 is their harmonic mean. "Fixes traced"
counts fixes for which at least one named commit is a true introducer.

bug-age ranks its nominees by blamed lines and calls the first the primary nominee; the lifetime
it reports is measured from that commit. It is scored both ways: all nominees, and the primary
nominee alone. PyDriller does not rank, so all its commits are scored.

## Results

All 83 fixes:

| | Named | Correct | Precision | Recall | F1 | Fixes traced |
|---|---|---|---|---|---|---|
| bug-age, primary nominee | 72 | 49 | 0.68 | 0.59 | 0.63 | 49 of 83 |
| bug-age, all nominees | 119 | 58 | 0.49 | 0.70 | 0.57 | 58 of 83 |
| PyDriller B-SZZ | 126 | 64 | 0.51 | 0.77 | 0.61 | 64 of 83 |

Six fixes change only test files. The `python` profile leaves tests out by design, because
bug-age measures bugs in product code, so it names no commit for them; PyDriller traces all six,
and they are the only fixes PyDriller traces that bug-age does not. No fix is traced by bug-age
and missed by PyDriller. On the 77 fixes that change product code:

| | Named | Correct | Precision | Recall | F1 | Fixes traced |
|---|---|---|---|---|---|---|
| bug-age, primary nominee | 72 | 49 | 0.68 | 0.64 | 0.66 | 49 of 77 |
| bug-age, all nominees | 119 | 58 | 0.49 | 0.75 | 0.59 | 58 of 77 |
| PyDriller B-SZZ | 120 | 58 | 0.48 | 0.75 | 0.59 | 58 of 77 |

Read together: on product code, bug-age's nominees find the same true introducers as PyDriller.
Its primary nominee, the one its numbers are built on, is right more often than either full list,
at the cost of missing the introducer when it is not the most-blamed commit. Neither tool reaches
the developers' answer for about a quarter of the fixes, which is the known limit of blame-based
SZZ; Method B exists to check individual results by behaviour.

Run on bug-age 2.2.2, PyDriller 2.12 and git 2.50.1. Every fix and each tool's named commits are
in `results/oracle/fixes.json`, and the totals in `results/oracle/summary.json`.

## Rerunning it

```sh
curl -sLo work/bugfix_commits_all.json https://raw.githubusercontent.com/grosa1/icse2021-szz-replication-package/45a712d1508745b0d60e779d1bbc5035d1647b34/json-input-raw/bugfix_commits_all.json
python3 -m venv work/venv && work/venv/bin/pip install pydriller==2.12
work/venv/bin/python scripts/oracle_study.py run --oracle work/bugfix_commits_all.json \
    --repos results/oracle/repos.tsv --work work/oracle-study --out results/oracle
```

The run clones the 80 repositories (about 100 MB) and takes about a minute after that.
`scripts/oracle_study.py select` rebuilds `repos.tsv` from the GitHub API; repository sizes
change over time, so a new selection may differ from the committed one.
