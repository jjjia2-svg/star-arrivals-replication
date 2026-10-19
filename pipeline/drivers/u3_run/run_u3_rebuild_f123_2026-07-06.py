"""First real-data run driver of the U3 panel (reproducible archive) — full two-school population (person_map: 162,000 people).

Injection follows run_smoke_m1 (same as the full U1 run): registry = the full snapshot education set ->
registry_by_id -> econ_dept_ids = the fixed table-A fold. Input = the u3_input_view_2026-07-06 view root
(symlinks to u1_edges_full_2026-07-05 + u2_person_map_2026-07-05, see the view README)."""
import json, pathlib, sys, time

# --- M3 port: repo path resolution (legacy hard-coded the author's machine) — config/paths.yaml ---
import pathlib as _sar_pl, sys as _sar_sys
_sar_repo = _sar_pl.Path(__file__).resolve().parents[3]
if str(_sar_repo) not in _sar_sys.path:
    _sar_sys.path.append(str(_sar_repo))
from pipeline.lib.paths import (derived_root as _sar_derived_root,  # noqa: E402,F401
                                snapshot_root as _sar_snapshot_root,
                                ssd_root as _sar_ssd_root,
                                legacy_thesis as _sar_legacy_thesis,
                                require_readable as _sar_rd,
                                require_writable as _sar_rw,
                                output_target as _sar_out,
                                deferred_output_target as _sar_lazyout)

_HERE = pathlib.Path(__file__).resolve().parents[2]
sys.path[:0] = [str(_HERE / p) for p in (
    "units/u0_foundation/src", "units/u0p5_dept_roster/src",
    "units/u1_fetch/src", "units/u3_panel/src")]

from identity.constants import build_registry_by_id
from m1_ingest.registry_build import load_education_registry
from roster.table_a import build_table_a_rows, build_econ_dept_ids
from m3_panel.panel import build_panel

SNAPSHOT = str(_sar_rd(_sar_snapshot_root()))
DATA_ROOT = str(_sar_rd(_sar_ssd_root() / "u3_input_view_2026-07-06"))
OUT = str(_sar_out(_sar_rw(_sar_derived_root()) / "u3_panel_2026-07-06"))

t0 = time.time()
print("① building registry (full education snapshot)...", flush=True)
registry = load_education_registry(SNAPSHOT)
registry_by_id = build_registry_by_id(registry)
econ_dept_ids = build_econ_dept_ids(build_table_a_rows(), registry_by_id)
print(f"   registry {len(registry_by_id):,} institutions, econ_dept_ids={sorted(econ_dept_ids)} ({time.time()-t0:.0f}s)", flush=True)

print("② starting build_panel...", flush=True)
result = build_panel(DATA_ROOT, OUT, econ_dept_ids=econ_dept_ids,
                     registry_by_id=registry_by_id, resume=False)
print(f"③ done ({(time.time()-t0)/60:.1f} min)", flush=True)
print(json.dumps(result, ensure_ascii=False, indent=1, default=str)[:2000], flush=True)
