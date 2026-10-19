"""U3 thin CLI - argparse → build_panel. No business logic here (all logic is in src/m3_panel/panel.py).

Usage (★data-root = the SSD root, not including derived; same convention as U2, the code appends derived/ internally):
  python -m units.u3_panel.run_u3 --data-root "<SSD>/openalex_pipeline" \
      --out-dir "<SSD>/openalex_pipeline/derived/u3_panel" --resume

Needs duckdb/pyarrow; a real-data smoke run (Monash+UNSW slice) comes before the full run.
"""
import argparse


def main(argv=None):
    parser = argparse.ArgumentParser(description="U3 panel build (panel + affil_timeline)")
    parser.add_argument("--data-root", required=True,
                        help="SSD root (excluding derived; the code joins derived/u1_edges/ and derived/u2_resolve/)")
    parser.add_argument("--out-dir", required=True, help="U3 output location (derived/u3_panel)")
    parser.add_argument("--no-resume", dest="resume", action="store_false",
                        help="Disable resume (enabled by default: skip when the upstream sha is unchanged)")
    parser.set_defaults(resume=True)
    args = parser.parse_args(argv)

    # Deferred import: build_panel is grown step by step under TDD.
    from m3_panel.panel import build_panel  # noqa: PLC0415

    raise SystemExit(
        "run_u3 needs econ_dept_ids / registry_by_id injected by the orchestrator; "
        "standalone CLI wiring is left to the U6 assembly stage (see the boundary in CONTRACT.md)."
    )


if __name__ == "__main__":
    main()
