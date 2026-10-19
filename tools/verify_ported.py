#!/usr/bin/env python3
"""A sha256 manifest of every tracked file under `pipeline/` — the layer's always-on guard.

**Why this exists.** The comparison of each ported file with the author's original code needs that
original code, which is private. On a replicator's checkout nothing can compare the port against it,
and a review showed what that costs: a silent `and aage >= 2` inside `72_restake_fnfix_stars.py`,
which changes the definition of a star, passed every other check.

So the bytes are recorded here instead. This manifest is not a substitute for the verbatim proofs —
it cannot tell a legitimate edit from a smuggled one, and the same commit that changes a file can
regenerate it. What it does is make the change **visible and deliberate everywhere**: a diff line in
review, on a machine where nothing else would have said anything at all.

    python3 tools/verify_ported.py            # check, prints PORTED_OK
    python3 tools/verify_ported.py --write    # regenerate after a deliberate port change

The manifest deliberately lives OUTSIDE `pipeline/` (a file inside the layer would have to hash
itself) and covers exactly `git ls-files pipeline` (every file under `pipeline/` outside a git
checkout), so an unexpected file is reported as ADDED.
"""
from __future__ import annotations

import hashlib
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
MANIFEST = REPO / "tests" / "pipeline_ported.sha256"


def tracked() -> list[str]:
    """`git ls-files pipeline` in a git checkout; every file under pipeline/ otherwise (for example an
    unpacked release archive), skipping Python caches."""
    r = subprocess.run(["git", "ls-files", "pipeline"], cwd=REPO, capture_output=True, text=True)
    if r.returncode == 0 and r.stdout.strip():
        return sorted(r.stdout.split())
    skip = {"__pycache__", ".pytest_cache"}
    return sorted(f.relative_to(REPO).as_posix() for f in (REPO / "pipeline").rglob("*")
                  if f.is_file() and not (skip & set(f.parts)) and f.name != ".DS_Store")


def current() -> dict[str, str]:
    return {rel: hashlib.sha256((REPO / rel).read_bytes()).hexdigest() for rel in tracked()
            if (REPO / rel).is_file()}


def recorded() -> dict[str, str]:
    if not MANIFEST.is_file():
        return {}
    out = {}
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        sha, rel = line.split("  ", 1)
        out[rel] = sha
    return out


def render(now: dict[str, str]) -> str:
    head = ("# sha256 of every tracked file under pipeline/ — see tools/verify_ported.py.\n"
            "# Regenerate with `python3 tools/verify_ported.py --write` in the SAME commit as any\n"
            "# deliberate change to the ported layer.\n")
    return head + "".join(f"{sha}  {rel}\n" for rel, sha in sorted(now.items()))


def diff() -> list[str]:
    now, was = current(), recorded()
    problems = [f"CHANGED  {rel}\n    recorded {was[rel]}\n    actual   {now[rel]}"
                for rel in sorted(set(now) & set(was)) if now[rel] != was[rel]]
    problems += [f"ADDED    {rel} (not in the manifest)" for rel in sorted(set(now) - set(was))]
    problems += [f"REMOVED  {rel} (in the manifest, not in the tree)"
                 for rel in sorted(set(was) - set(now))]
    return problems


def main(argv: list[str]) -> int:
    if "--write" in argv:
        MANIFEST.write_text(render(current()), encoding="utf-8")
        print(f"wrote {MANIFEST.relative_to(REPO)}: {len(current())} files")
        return 0
    problems = diff()
    if problems:
        print("PORTED_MANIFEST_STALE:\n  " + "\n  ".join(problems))
        print("\nIf the change is intended, run `python3 tools/verify_ported.py --write` and commit\n"
              "the manifest alongside it, so the edit is visible on machines that have no legacy tree.")
        return 1
    print(f"PORTED_OK ({len(current())} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
