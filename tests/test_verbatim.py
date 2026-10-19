"""Hard rule 1: every analysis/estimation/*.R driver is a verbatim copy of its legacy source,
apart from the header comment the repo added and the $SAR_OUT output-directory edit.

For each driver: read the legacy source path + sha256 out of its own header comment, check that
sha256 against the legacy file, then undo the repo's two edits and require byte equality.
Skips when the legacy tree is not on this machine (author-only read-only source)."""
import hashlib, pathlib, re, sys
import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from analysis.lib.paths import load_paths

SHEBANG = "#!/usr/bin/env Rscript"
# the repo's two permitted edits, and how to map them back to the legacy line
OUT_REPO = 'OUT <- Sys.getenv("SAR_OUT", "out"); dir.create(OUT, showWarnings=FALSE, recursive=TRUE)   # repo edit: output dir from env (was fixed "out")'
OUT_LEGACY = 'dir.create("out", showWarnings=FALSE)'
HEADER_RE = re.compile(r"^# Verbatim copy of (v2_output/\S+\.R) \(sha256 ([0-9a-f]{64})\)")

DRIVERS = sorted((REPO / "analysis/estimation").glob("*.R"))


def sha(b: bytes) -> str: return hashlib.sha256(b).hexdigest()


@pytest.mark.parametrize("driver", DRIVERS, ids=lambda d: d.name)
def test_driver_is_verbatim(driver):
    repo_lines = driver.read_text().split("\n")
    assert repo_lines[0] == SHEBANG, driver.name

    m = HEADER_RE.match(repo_lines[1])
    assert m, f"{driver.name}: line 2 must name the legacy source and its sha256"
    rel, want_sha = m.group(1), m.group(2)

    legacy = load_paths()["legacy_v2_output"] / rel[len("v2_output/"):]
    if not legacy.exists():
        pytest.skip(f"legacy source not on this machine: {legacy}")

    legacy_bytes = legacy.read_bytes()
    assert sha(legacy_bytes) == want_sha, f"{driver.name}: legacy source hash != the hash in the header"

    legacy_lines = legacy_bytes.decode().split("\n")
    assert legacy_lines[0] == SHEBANG, rel

    # (a) drop the header block the repo inserted: everything between the shebang and the legacy's own line 2
    n = repo_lines.index(legacy_lines[1], 1)
    header = repo_lines[1:n]
    assert header and all(h.startswith("#") for h in header), f"{driver.name}: header block is not all comments"
    stripped = [repo_lines[0]] + repo_lines[n:]

    # (b) undo the $SAR_OUT edit
    undone = "\n".join(stripped).replace(OUT_REPO, OUT_LEGACY).replace('file.path(OUT,', 'file.path("out",')

    assert undone == legacy_bytes.decode(), f"{driver.name}: differs from {rel} beyond the header and the SAR_OUT edit"


def test_all_seven_drivers_present():
    assert len(DRIVERS) == 7, [d.name for d in DRIVERS]
