"""Verify a sha256 manifest (sha256sum -c semantics). Exit 0 iff all match.

Usage: python3 tools/verify_manifest.py [manifest]   (default: data/MANIFEST.sha256)
Listed paths are resolved against the repo root; if that misses, against the manifest's own
directory (analysis/expected/MANIFEST.sha256 lists bare file names). A manifest inside a canon (an
ancestor directory holds CANON.json) resolves its keys against that canon root, then its own
directory, never the repo root (canon keys are '<key>/<rel>', e.g. frames/p1_frame_econ.csv)."""
import hashlib, sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
man = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path("data/MANIFEST.sha256")
if not man.is_absolute(): man = ROOT / man


def canon_root(m):
    """The nearest ancestor of the manifest holding CANON.json (the repo root itself excluded), or None."""
    d, stop = m.resolve().parent, ROOT.resolve()
    while d != stop:
        if (d / "CANON.json").is_file(): return d
        if d.parent == d: return None
        d = d.parent
    return None


canon = canon_root(man)
bases = [canon, man.parent] if canon else [ROOT, man.parent]
bad = 0
for line in man.read_text().splitlines():
    if not line.strip(): continue
    h, rel = line.split("  ", 1)
    f = next((b / rel for b in bases if (b / rel).exists()), bases[-1] / rel)
    ok = f.exists() and hashlib.sha256(f.read_bytes()).hexdigest() == h
    if not ok: bad += 1; print("MISMATCH", rel)
print("MANIFEST_OK" if not bad else f"MANIFEST_FAIL {bad}")
sys.exit(1 if bad else 0)
