"""Write a sha256 MANIFEST for one artifact directory (sha256sum -c semantics; verified by
tools/verify_manifest.py, which resolves bare names against the manifest's own directory).

Usage: python3 tools/write_manifest.py <dir> [<dir> ...]

Every regular file under <dir> (recursively) is listed, except MANIFEST.sha256 itself and
.DS_Store. Paths are written RELATIVE TO THE REPOSITORY ROOT (data/<dir>/<file>), the form
data/MANIFEST.sha256 uses, because tools/verify_manifest.py resolves a listed path against the
repo root FIRST and only then against the manifest's own directory — a bare `README.md` would be
checked against the repo's top-level README, not the directory's. Existing lines are NOT trusted: the manifest is rewritten
from the bytes on disk, so run it only when the directory is the state you mean to freeze."""
import hashlib, pathlib, sys

SKIP = {"MANIFEST.sha256", ".DS_Store"}
ROOT = pathlib.Path(__file__).resolve().parents[1]


def write(d: pathlib.Path) -> int:
    d = d.resolve()
    base = ROOT if d.is_relative_to(ROOT) else d
    files = sorted(p for p in d.rglob("*") if p.is_file() and p.name not in SKIP)
    lines = [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(base).as_posix()}"
             for p in files]
    (d / "MANIFEST.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(lines)


def main(argv):
    if len(argv) < 2:
        print(__doc__); return 2
    for a in argv[1:]:
        d = pathlib.Path(a)
        if not d.is_dir():
            print(f"not a directory: {a}"); return 1
        print(f"{d}: {write(d)} files pinned")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
