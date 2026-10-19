#!/usr/bin/env bash
# Refresh the sha256 pins of the REPO_AUTHORED files in tests/test_verbatim_pipeline.py.
#
# Those five files - the layer's README, the drivers README (which carries the gap register and the
# per-driver overwrite table), lib/paths.py, frames/make_slim.py and drivers/run_driver.py - are
# pinned because they are the only files under pipeline/ that no verbatim test reviews, and because
# two of the safety claims in the drivers README were found to be false during review. Editing one
# is meant to be a deliberate act; this script makes it a mechanical one instead of hand-copying
# 64-character strings.
#
#   tools/repin.sh            # rewrite the pins in place, then print what changed
#   tools/repin.sh --check    # exit 1 if any pin is stale (what CI/the test already does)
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
LEDGER="$REPO/tests/test_verbatim_pipeline.py"
MODE="${1:-write}"

python3 - "$REPO" "$LEDGER" "$MODE" <<'PY'
import hashlib, pathlib, re, sys
repo, ledger, mode = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]), sys.argv[3]
text = ledger.read_text(encoding="utf-8")
block = re.search(r"REPO_AUTHORED: dict\[str, tuple\[str, str\]\] = \{(.*?)\n\}", text, re.S)
if not block:
    sys.exit("could not find the REPO_AUTHORED declaration")
rels = re.findall(r'"([^"]+)": \(\n        "[0-9a-f]{64}"', block.group(1))
stale, out = [], text
for rel in rels:
    f = repo / rel
    if not f.is_file():
        sys.exit(f"{rel} is declared REPO_AUTHORED but is not in the tree")
    want = hashlib.sha256(f.read_bytes()).hexdigest()
    pat = re.compile(r'("' + re.escape(rel) + r'": \(\n        ")([0-9a-f]{64})(")')
    m = pat.search(out)
    if m.group(2) != want:
        stale.append(f"{rel}\n    {m.group(2)}  ->  {want}")
        out = pat.sub(lambda mm: mm.group(1) + want + mm.group(3), out, count=1)
if mode == "--check":
    print("REPIN_OK" if not stale else "STALE PINS:\n  " + "\n  ".join(stale))
    sys.exit(1 if stale else 0)
if stale:
    ledger.write_text(out, encoding="utf-8")
    print("repinned:\n  " + "\n  ".join(stale))
else:
    print("REPIN_OK (nothing to do)")
PY
