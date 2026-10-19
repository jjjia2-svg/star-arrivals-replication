"""u0p5_hist_raw test import bridge — follows the u0p5 conftest convention (anchored on the units directory)."""
import pathlib
import sys

_here = pathlib.Path(__file__).resolve()
_units = next(p for p in _here.parents if p.name == "units")

U0_SRC = _units / "u0_foundation" / "src"
U0P5_SRC = _units / "u0p5_dept_roster" / "src"
HISTRAW_SRC = _units / "u0p5_hist_raw" / "src"

assert U0_SRC.exists(), f"U0 src not at the expected location: {U0_SRC}"
assert HISTRAW_SRC.exists(), f"histraw src not at the expected location: {HISTRAW_SRC}"

assert U0P5_SRC.exists(), f"u0p5 src not at the expected location: {U0P5_SRC}"

for _p in (str(U0_SRC), str(U0P5_SRC), str(HISTRAW_SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)
