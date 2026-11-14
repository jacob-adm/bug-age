# Getting started

Point bug-age at your own repository, run it, and read the result.

## Get started

Point bug-age at your own repository in six steps. A first run with Method A only needs git and Python; Docker is needed only for the feasibility check and Method B.

**1. Install.**

```sh
pip install bug-age                                       # Python 3.11 or later, no dependencies
bug-age dockerfile | docker build -t bug-age-spike:4 -    # only for feasibility and Method B
```

You also need git. The Docker image name `bug-age-spike:4` is the CLI default; pass `--image` to use another.

**2. Describe your repository in a config file.** Copy an existing one and edit it:

```sh
curl -sO https://raw.githubusercontent.com/jacob-adm/bug-age/main/targets/rust-sdk.toml
mkdir -p targets && mv rust-sdk.toml targets/myrepo.toml
```

| Key | Required | What to set |
|---|---|---|
| `name` | yes | Short name: lowercase letters, digits and `-`. Used in file names and the explorer. |
| `repo_url` | yes | Clone URL of the repository. |
| `head` | yes | Full SHA of the commit to analyse up to. Pinning it makes the run reproducible. |
| `crate_path` | yes | Directory of the crate inside the repository (`.` for the root). Only history under this path is analysed. |
| `work_dir`, `results_dir`, `spike_dir`, `dist_dir` | yes | Where the clone, results, feasibility reports and bundle go, relative to this repository. Follow the pattern `work/<name>`, `results/<name>`, `results/<name>/spike`, `dist/<name>`. |
| `release_tag_glob` | no | Pattern matching your release tags, for release counts. Default `v[0-9]*`. Set it if your tags look different, e.g. `mycrate-v[0-9]*`, or every release count will be 0. |
| `package` | no | Cargo package to build and test in a workspace. Default: the whole workspace. |
| `samples` | no | Commits sampled by the feasibility check. Default 20. |
| `szz_window_start` | no | `YYYY-MM-DD`. Flags fixes whose introducer falls on or after this date. |
| `out_of_scope` | no | `STAGE\|EVIDENCE\|DOES_NOT_PROVE`: a part of the repository you deliberately leave out, listed as NOT TESTED. |

**3. Run the pipeline.**

```sh
bug-age pipeline targets/myrepo.toml --skip-feasibility   # Method A only, no Docker
bug-age pipeline targets/myrepo.toml                       # adds the Docker feasibility check
```

**4. Read the report.** `results/myrepo/PIPELINE.md` lists every stage with its status (OK, REUSED, FAILED or NOT TESTED), the reason, and the time taken. The bundle, `dist/myrepo/bundle.json`, is the report of record: every number for this repository is in it. Its sha256 and the exact command that built it are in `dist/myrepo/receipt.json`.

**5. Browse the report in your own explorer.** This builds a viewer for your bundle on your machine. The published live example is not affected and keeps showing only the two example runs. To browse several of your repositories together, list them all: `--targets a=dist/a,b=dist/b`.

```sh
bug-age explorer --targets myrepo=dist/myrepo --out dist/explorer-myrepo
open dist/explorer-myrepo/index.html        # or open the file in any browser
```

**6. Optional: date selected bugs by testing (Method B).** Pick a fix from `results/myrepo/catalog.json` and add a regression test at `results/myrepo/repros/<first 10 chars of the fix SHA>/overlay/tests/bugage_repro.rs`. The overlay is copied into the crate at every commit tested, so the test can only use the crate's public API. It must fail at the commit just before the fix and pass at the fix; otherwise the sweep rejects it as `repro-invalid`. Run step 3 again: Method B runs whenever a regression test has no sweep yet. See `results/tokenizers/repros/` for six examples.
