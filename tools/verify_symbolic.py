#!/usr/bin/env python3
"""Check the sha256 pins of the SYMBOLIC normalisation of every patched or recovered file under
`pipeline/`.

**What this adds that `tools/verify_ported.py` does not.** That manifest records the bytes, so a
replicator can see that a ported file has not changed since it was published. It cannot say what the
port changed relative to the author's original code, because that original code is private.

The symbolic form closes that. `_normalise()` (in `tests/test_verbatim_pipeline.py`) undoes the
port's substitutions, folding each resolver call back to the literal it resolves to on THIS machine;
`_symbolise()` folds that literal one step further, to a fixed token. Doing both to the port, and just
the second to the original file, lands on the same text:

    ported  --normalise-->  original text  --symbolise-->  symbolic  ==  original --symbolise--> symbolic

The pins in `tests/pipeline_symbolic.sha256` were recorded from the ORIGINAL sources (or, for a
RECOVERED file, from the replay of the author's working records) in the author's private
repository, where the sources are present. This public copy only checks them; a pin cannot be minted
here, because a pin derived from the port itself would prove nothing. Exception: where the public copy
had to change a pinned file's text (person names replaced by author ids, process wording removed), the
export re-minted the pin from the published port and lists the file in HASH_CROSSWALK.md with its
private and public sha256; for those files the pin proves only that the published port is unchanged.

    python3 tools/verify_symbolic.py            # check, prints SYMBOLIC_OK

Only PATCHED and RECOVERED files are pinned here. A byte-identical ported file contains no machine
literal at all, so its symbolic form IS its bytes and `tests/pipeline_ported.sha256` already covers
it.
"""
from __future__ import annotations

import hashlib
import importlib.util
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
MANIFEST = REPO / "tests" / "pipeline_symbolic.sha256"


def _ledger():
    """The verbatim test module, imported for its declarations and its normaliser."""
    spec = importlib.util.spec_from_file_location(
        "sar_verbatim_ledger", REPO / "tests" / "test_verbatim_pipeline.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def current(mod=None) -> dict[str, str]:
    """What the PORT normalises to - what a replicator's copy must reproduce."""
    mod = mod or _ledger()
    rels = sorted(set(mod.PATCHED) | set(mod.RECOVERED))
    return {rel: hashlib.sha256(mod.symbolic_form(rel).encode("utf-8")).hexdigest()
            for rel in rels}


def recorded() -> dict[str, str]:
    out = {}
    if MANIFEST.is_file():
        for line in MANIFEST.read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.startswith("#"):
                sha, rel = line.split("  ", 1)
                out[rel] = sha
    return out


def main(argv: list[str]) -> int:
    if "--write" in argv:
        print("refusing to write: symbolic pins are minted against the private original sources, "
              "in the author's private repository. This public copy can only check them.")
        return 1
    now, was = current(), recorded()
    problems = [f"CHANGED  {rel}\n    recorded {was[rel]}\n    actual   {now[rel]}"
                for rel in sorted(set(now) & set(was)) if now[rel] != was[rel]]
    problems += [f"UNPINNED {rel}" for rel in sorted(set(now) - set(was))]
    problems += [f"STALE    {rel} (pinned, no longer patched or recovered)"
                 for rel in sorted(set(was) - set(now))]
    if problems:
        print("SYMBOLIC_STALE:\n  " + "\n  ".join(problems))
        return 1
    print(f"SYMBOLIC_OK ({len(now)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
