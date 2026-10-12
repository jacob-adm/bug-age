"""BUGAGE-5: build a crates.io index "as of" a timestamp, for commits that never committed a Cargo.lock.

The crates.io sparse index records `pubtime` for every version. For a cutoff time we keep only the
versions published by then, write them in the classic git-index layout (readable by every cargo
release) and let the commit's own toolchain resolve against it via source replacement.

Known approximation: yank state in the index is today's. Versions kept by the cutoff are un-yanked
(they were installable then); the count is reported so results can be qualified.
"""
from __future__ import annotations

import json, subprocess, tomllib, urllib.error, urllib.request
from pathlib import Path

SPARSE = "https://index.crates.io"
DL = "https://crates.io/api/v1/crates"     # pre-template dl form: works for old and new cargo
DEP_TABLES = ("dependencies", "dev-dependencies", "build-dependencies")


def index_path(name: str) -> str:
    n = name.lower()
    if len(n) <= 2:
        return f"{len(n)}/{n}"
    if len(n) == 3:
        return f"3/{n[0]}/{n}"
    return f"{n[:2]}/{n[2:4]}/{n}"


def fetch_entries(name: str, cache: Path) -> list[dict]:
    """All index lines for a crate (cached on disk; [] if the crate is not on crates.io)."""
    f = cache / index_path(name)
    if not f.is_file():
        req = urllib.request.Request(f"{SPARSE}/{index_path(name)}", headers={"User-Agent": "bug-age-spike (BUGAGE-5)"})
        try:
            body = urllib.request.urlopen(req, timeout=60).read().decode()
        except urllib.error.HTTPError as e:
            if e.code in (403, 404, 410):
                body = ""
            else:
                raise
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(body)
    return [json.loads(l) for l in f.read_text().splitlines() if l.strip()]


def manifest_deps(tree: Path, manifest: Path, seen: set[Path]) -> set[str]:
    """Registry dependency names of a manifest, following path dependencies and workspace members."""
    manifest = manifest.resolve()
    if manifest in seen or not manifest.is_file():
        return set()
    seen.add(manifest)
    doc = tomllib.loads(manifest.read_text())
    tables = [doc.get(t, {}) for t in DEP_TABLES]
    tables += [doc.get("workspace", {}).get("dependencies", {})]
    for target in doc.get("target", {}).values():
        tables += [target.get(t, {}) for t in DEP_TABLES]
    names: set[str] = set()
    for table in tables:
        for key, spec in table.items():
            if isinstance(spec, dict) and "path" in spec:
                names |= manifest_deps(tree, manifest.parent / spec["path"] / "Cargo.toml", seen)
            elif not (isinstance(spec, dict) and ("git" in spec or spec.get("workspace"))):
                names.add(spec.get("package", key) if isinstance(spec, dict) else key)
    for member in doc.get("workspace", {}).get("members", []):
        for m in sorted(manifest.parent.glob(member)):
            names |= manifest_deps(tree, m / "Cargo.toml", seen)
    return names


def build_index(tree: Path, crate_dir: str, cutoff: str, cache: Path, out: Path) -> dict:
    """Write a git index of all crates reachable from the workspace, filtered to pubtime <= cutoff.
    `cutoff` is an ISO-8601 UTC timestamp (YYYY-MM-DDTHH:MM:SSZ), comparable as a string."""
    roots = manifest_deps(tree, tree / crate_dir / "Cargo.toml", set())
    todo, done = sorted(roots), set()
    kept_versions = unyanked = 0
    out.mkdir(parents=True, exist_ok=True)
    while todo:
        name = todo.pop()
        if name.lower() in done:
            continue
        done.add(name.lower())
        lines = [e for e in fetch_entries(name, cache) if e.get("pubtime", "9999") <= cutoff]
        if not lines:
            continue
        for e in lines:
            unyanked += bool(e.get("yanked"))
            e["yanked"] = False
            todo.extend(d.get("package", d["name"]) for d in e.get("deps", []))
        kept_versions += len(lines)
        f = out / index_path(name)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("".join(json.dumps(e, separators=(",", ":")) + "\n" for e in lines))
    crates = sum(1 for f in out.rglob("*") if f.is_file())
    (out / "config.json").write_text(json.dumps({"dl": DL, "api": "https://crates.io"}))
    env = {"GIT_AUTHOR_NAME": "bug-age", "GIT_AUTHOR_EMAIL": "bug-age@invalid", "GIT_COMMITTER_NAME": "bug-age",
           "GIT_COMMITTER_EMAIL": "bug-age@invalid", "GIT_CONFIG_GLOBAL": "/dev/null", "PATH": "/usr/bin:/bin"}
    for cmd in (["init", "-q", "-b", "master"], ["add", "-A"], ["commit", "-q", "-m", f"index as of {cutoff}"]):
        subprocess.run(["git", "-C", str(out), *cmd], check=True, env=env, capture_output=True)
    return {"cutoff": cutoff, "root_crates": len(roots), "crates": crates,
            "versions": kept_versions, "unyanked": unyanked}
