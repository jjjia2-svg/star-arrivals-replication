# data/estimates

Archived result JSONs that the thesis cites but that this repo does not
reproduce locally: the cloud-only P3 event-cluster runs for economics and
chemistry (`P3evcl_econ.json`, `P3evcl_chemistry.json`), the econ
no-zero-roster robustness result, and the event-cluster summary JSON. These
are frozen copies — byte-identical to the legacy source, verified against
`data/MANIFEST.sha256` — imported from the legacy `v2_output/` trees
`cluster_event_2026-08-16/` and `econ_final_2026-08-13/` (see
`tools/import_frozen.py` for the exact per-file mapping); never edit them
here. The chain-of-custody logs for the cloud runs that produced these (and
the other P3 cloud estimates already frozen in `analysis/expected/`) live in
`pipeline/aws/logs/`. `P3evcl_econ.json` and `P3evcl_chemistry.json` are also frozen in
`analysis/expected/` (byte-identical copies) so that `tools/compare_all.py` reports them as
VERIFIED_NOT_RERUN alongside the other two cloud cells; the copies here are the archive.
