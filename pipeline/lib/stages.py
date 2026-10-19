"""The pipeline layer's stage inventory, read from the launchers rather than restated beside them.

`pipeline/run_all.sh` needs to know three things about every stage: which layer it belongs to,
whether it runs by default, and — when it does not — WHY it is off. All three already exist, in each
launcher's own `STAGES` object, and that is where they must stay: a stage list copied into a shell
script is a second declaration that drifts (the repository has been bitten by exactly that twice,
with the driver coverage test and the frames acceptance table). So this module imports the four
launchers and reports what they declare.

Two things are declared here rather than derived, and they answer different questions.

**`REQUIRES` — what a stage NEEDS.** M3 Task 8's review found the default run documented as
self-contained when it is not: with the read-only legacy trees absent, 14 of the 15 default stages
fail; with the data disk absent, 3 do. The cost class never carried that fact, so nothing said it and
nothing checked it. It is now its own axis, `{} | {"legacy"} | {"disk"} | {"legacy","disk"}`, and
`tests/test_pipeline_rebuild.py` proves the declaration by RUNNING the default plan with each root
pointed somewhere empty — not by re-reading the declaration, which is how the first version of that
test passed while being wrong.

**`COST_CLASS` — how expensive a stage is**, because "off by default" covers three different
situations that a replicator must be able to tell apart:

    ssd    free, minutes, needs the data disk mounted. These are what `--with-ssd` turns on, and
           they are the rest of the rebuild proof — the frames whose builders read the 24 GB edge
           tables, and the two star rankings.
    long   free, but the machine is busy for over half an hour: the 37-minute full-snapshot FWCI
           scan. `--expensive`, with its cost printed first.
    api    calls the LIVE OpenAlex API. Off under every flag, because a fresh call today returns
           DIFFERENT data — that is the address back-fill defect the fn-fix exists to correct — so
           running one is not a reproduction, it is a new measurement.

The classes are declared, not inferred from the gate text, and `tests/test_pipeline_rebuild.py`
asserts the declaration covers exactly the gated stages the launchers hold.

    python3 -m pipeline.lib.stages                    # every stage: layer, stage, class, requires
    python3 -m pipeline.lib.stages --plan default     # a tab-separated run plan for run_all.sh
    python3 -m pipeline.lib.stages --plan default,ssd --layer frames
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.append(str(REPO))

#: layer -> the launcher that owns it, in the order `run_all.sh` runs them. The order is the data
#: dependency: rosters define the population, stars pick the events, fwci builds the denominators,
#: frames assemble the estimation panels from all three.
LAYERS: tuple[tuple[str, str], ...] = (
    ("rosters", "pipeline/rosters/run_rosters.py"),
    ("stars", "pipeline/stars/run_stars.py"),
    ("fwci", "pipeline/fwci/run_fwci.py"),
    ("frames", "pipeline/frames/run_frames.py"),
)

#: "<layer>:<stage>" -> cost class, for every stage that is NOT on by default. See the module
#: docstring. A stage missing from here, or one here that is no longer gated, fails the test.
COST_CLASS: dict[str, str] = {
    "rosters:fnfix": "api",
    "stars:restake": "ssd",
    "stars:suspects": "ssd",
    "stars:prescreen": "api",
    "stars:prefetch": "api",
    "fwci:scan": "long",
    "frames:union-gold": "ssd",
    "frames:p1-gold": "ssd",
    "frames:p2-gold": "ssd",
    "frames:p2-econ": "ssd",
    "frames:p1-econ": "ssd",
}

#: stages a gated run still cannot reach with `--execute`, and why. `rosters:fnfix` has no
#: `--execute` at all (its launcher offers none); `stars:prefetch` registers no output.
NO_EXECUTE: dict[str, str] = {
    "rosters:fnfix": "the roster launcher offers no --execute for it: its only effect this layer "
                     "needs is a shutil.copyfile that tests/test_pipeline_rebuild.py asserts",
    "stars:prefetch": "it takes author ids as arguments and registers no output, so there is "
                      "nothing for a whole-layer run to compare",
}


#: "<layer>:<stage>" -> what the stage NEEDS beyond this repository. MEASURED, not guessed: the
#: default plan is re-run in `tests/test_pipeline_rebuild.py` with `legacy_v2_output` and then
#: `ssd_root` pointed at empty directories (through `$SAR_PATHS_CONFIG`), and exactly the stages
#: declared here must fail. The measurement on 2026-08-26:
#:
#:     no legacy tree ->  1 of 15 default stages survives (fwci/build, because of T8's NEWPOP shim)
#:     no data disk   -> 12 of 15 survive (rosters/econ-audit, stars/u4aug, fwci/build fail)
#:
#: so NOTHING in the default set is repo-only, and saying otherwise was the review's MAJOR-1.
#: `legacy` means `legacy_v2_output` / `legacy_thesis`; `disk` means `ssd_root`.
REQUIRES: dict[str, frozenset[str]] = {
    "rosters:merge":           frozenset({"legacy"}),
    "rosters:variants":        frozenset({"legacy"}),
    "rosters:incfel":          frozenset({"legacy"}),
    "rosters:final":           frozenset({"legacy"}),
    "rosters:econ-audit":      frozenset({"legacy", "disk"}),
    "rosters:econ-merge":      frozenset({"legacy"}),
    "rosters:fnfix":           frozenset({"legacy"}),
    "stars:candidates":        frozenset({"legacy"}),
    "stars:events-chemmath":   frozenset({"legacy"}),
    "stars:events-econ":       frozenset({"legacy"}),
    "stars:u4aug":             frozenset({"legacy", "disk"}),
    "stars:restake":           frozenset({"legacy", "disk"}),
    "stars:suspects":          frozenset({"legacy", "disk"}),
    "stars:prescreen":         frozenset({"legacy", "disk"}),
    "stars:prefetch":          frozenset({"legacy"}),
    "fwci:build":              frozenset({"disk"}),
    "fwci:scan":               frozenset({"disk"}),
    "frames:afar":             frozenset({"legacy"}),
    "frames:speed":            frozenset({"legacy"}),
    "frames:split":            frozenset({"legacy"}),
    "frames:ledger":           frozenset({"legacy"}),
    "frames:union-gold":       frozenset({"legacy", "disk"}),
    "frames:p1-gold":          frozenset({"legacy", "disk"}),
    "frames:p2-gold":          frozenset({"legacy", "disk"}),
    "frames:p2-econ":          frozenset({"legacy", "disk"}),
    "frames:p1-econ":          frozenset({"legacy", "disk"}),
}


def requires(layer: str, stage: str) -> frozenset:
    return REQUIRES[f"{layer}:{stage}"]


def needs_label(reqs) -> str:
    return "+".join(sorted(reqs)) if reqs else "repo-only"


#: extra command-line arguments a WHOLE-LAYER run must pass, because one stage covers several
#: outputs only when it is invoked once per field. Declared here rather than in `run_all.sh` for the
#: same reason the stage names are: one declaration, checked by a test (the frames these produce must
#: cover every frozen frame the layer claims to rebuild).
EXTRA_ARGS: dict[str, tuple[tuple[str, ...], ...]] = {
    "frames:p1-gold": (("--field", "chemistry"), ("--field", "math_stats")),
    "frames:p2-gold": (("--field", "chemistry", "--panel3", "full"),
                       ("--field", "math_stats", "--panel3", "full")),
}


def _load(rel: str):
    name = "sar_launcher_" + pathlib.Path(rel).stem
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod          # @dataclass resolves annotations through sys.modules
    spec.loader.exec_module(mod)
    return mod


def _gated(layer: str, stage, spec) -> bool:
    """Whether the launcher declares this stage OFF by default."""
    if layer == "fwci":                       # STAGES[name] = (script, outputs, modules, gated)
        return bool(spec[3])
    return getattr(spec, "gate", None) is not None


def inventory() -> list[tuple[str, str, str, frozenset]]:
    """`[(layer, stage, cost class, requirements)]` in run order; class is "default" if it runs."""
    rows = []
    for layer, rel in LAYERS:
        mod = _load(rel)
        for stage, spec in mod.STAGES.items():
            key = f"{layer}:{stage}"
            rows.append((layer, stage,
                         COST_CLASS.get(key, "UNCLASSIFIED") if _gated(layer, stage, spec)
                         else "default",
                         REQUIRES.get(key, frozenset({"UNDECLARED"}))))
    return rows


def launcher(layer: str) -> str:
    return dict(LAYERS)[layer]


def plan(classes: set[str], layers: set[str] | None = None) -> list[tuple[str, ...]]:
    """`[(layer, launcher, stage, class, *args)]` — one entry per launcher INVOCATION."""
    out = []
    for layer, stage, klass, _reqs in inventory():
        if klass not in classes or (layers and layer not in layers):
            continue
        key = f"{layer}:{stage}"
        if key in NO_EXECUTE:
            continue
        for args in EXTRA_ARGS.get(key, ((),)):
            out.append((layer, launcher(layer), stage, klass, *args))
    return out


def main(argv: list[str]) -> int:
    layers = {argv[argv.index("--layer") + 1]} if "--layer" in argv else None
    if "--plan" in argv:
        classes = set(argv[argv.index("--plan") + 1].split(","))
        for row in plan(classes, layers):
            print("\t".join(row))
        return 0
    for layer, stage, klass, reqs in inventory():
        if layers and layer not in layers:
            continue
        print(f"{layer} {stage} {klass} needs={needs_label(reqs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
