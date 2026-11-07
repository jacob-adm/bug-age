#!/usr/bin/env python3
"""Blameless check over bug-age's own git history, before the repository is made public.

    python3 scripts/history_scan.py --targets work/tokenizers,work/rust-sdk [--repo .] [--allow FILE]

Scans every blob reachable from any ref (each distinct file version once) and every commit message
for (1) the names, emails and noreply usernames of anyone in the target repositories' history, using
the same rules as the bundle gate (crates/bug-age/src/bundle.rs people()), and (2) any email address.
Prints one line per hit as `kind<TAB>where<TAB>match` and exits 1 if anything is not allowlisted.
The allowlist file holds one `kind<TAB>where<TAB>match` line per reviewed, accepted hit; `where` = `*`
accepts that match everywhere (only for matches that cannot identify a person).
"""
import argparse, re, subprocess, sys
from pathlib import Path

# Any email address, matched on raw bytes
EMAIL = re.compile(rb"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# Tokens from git identities that are not people
GENERIC = {"github", "noreply", "web-flow", "users.noreply.github.com"}
# The scanner's own files list the reviewed matches; there a hit passes only if that match is reviewed elsewhere.
SELF = {"scripts/history_scan.py", "scripts/history_scan.allow"}


def git(repo, *args):
    """Run git in `repo` and return stdout as bytes; raises on failure."""
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True).stdout


def people(repo):
    """Return every name, email and noreply username in a target repository's history (lower-cased)."""
    found = set()
    for line in git(repo, "log", "--all", "--format=%an%n%ae%n%cn%n%ce").decode("utf-8", "replace").splitlines():
        line = line.strip()
        if len(line) < 3:
            continue
        found.add(line.lower())
        if "@" in line:
            user = line.split("@", 1)[0].rsplit("+", 1)[-1]
            if len(user) >= 3:
                found.add(user.lower())
    return found - GENERIC


def main():
    """Scan every reachable blob and commit message, apply the allowlist, print open hits, and return 1 if any."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", required=True, help="comma-separated target clones")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--allow")
    a = ap.parse_args()
    names = set()
    for t in a.targets.split(","):
        names |= people(Path(t))
    alternation = b"|".join(re.escape(n.encode()) for n in sorted(names, key=len, reverse=True))
    who = re.compile(rb"(?i)(?<!\w)(" + alternation + rb")(?!\w)")
    allow = set()
    if a.allow and Path(a.allow).exists():
        allow = {l for l in Path(a.allow).read_text().splitlines() if l and not l.startswith("#")}

    hits = []
    # every distinct blob, with the first path it was seen at
    seen = {}
    for line in git(a.repo, "rev-list", "--all", "--objects").decode("utf-8", "replace").splitlines():
        sha, _, path = line.partition(" ")
        if path and sha not in seen:
            seen[sha] = path
    batch = subprocess.run(["git", "-C", a.repo, "cat-file", "--batch"], input="\n".join(seen).encode() + b"\n",
                           check=True, capture_output=True).stdout
    pos = 0
    while pos < len(batch):
        header_end = batch.index(b"\n", pos)
        sha, kind, size = batch[pos:header_end].split()
        size = int(size)
        body = batch[header_end + 1: header_end + 1 + size]
        pos = header_end + 1 + size + 1
        if kind != b"blob" or b"\0" in body[:8000]:
            continue
        where = seen[sha.decode()]
        for m in set(EMAIL.findall(body)):
            hits.append(("email", where, m.decode("utf-8", "replace")))
        for m in set(x.lower() for x in who.findall(body)):
            hits.append(("person", where, m.decode("utf-8", "replace")))
    for line in git(a.repo, "log", "--all", "--format=%H%x00%B%x01").decode("utf-8", "replace").split("\x01"):
        if "\x00" not in line:
            continue
        sha, msg = line.strip().split("\x00", 1)
        where = "commit: " + (msg.splitlines() or [""])[0][:80]
        for m in set(EMAIL.findall(msg.encode())):
            hits.append(("email", where, m.decode()))
        for m in set(x.lower() for x in who.findall(msg.encode())):
            hits.append(("person", where, m.decode()))

    hits = sorted(set(hits))
    reviewed = {line.split("\t")[2] for line in allow if line.count("\t") == 2}
    anywhere = {(l.split("\t")[0], l.split("\t")[2]) for l in allow if l.count("\t") == 2 and l.split("\t")[1] == "*"}
    open_hits = [h for h in hits if "\t".join(h) not in allow and (h[0], h[2]) not in anywhere
                 and not (h[1] in SELF and h[2] in reviewed)]
    for h in open_hits:
        print("\t".join(h))
    print(f"history scan: {len(seen)} objects, {len(names)} target identities, {len(hits)} hits, "
          f"{len(hits) - len(open_hits)} allowlisted, {len(open_hits)} open", file=sys.stderr)
    return 1 if open_hits else 0


if __name__ == "__main__":
    sys.exit(main())
