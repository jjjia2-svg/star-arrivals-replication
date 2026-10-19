"""M0-3 capacity_gate — capacity gate before fetching (derived-size gate + real remote-byte gate + per-shard space gate).

  - Reuses U0 common/preflight.{disk_gate_decision, preflight_disk_check} (NOT manifest.capacity_preflight;
    the function lives in preflight.py).
  - DATA_ROOT uses the U0 preflight constant (the derived/ directory); it is not redefined here.
  - Three gates:
      1. snapshot_capacity_gate: the derived size goes through disk_gate_decision (need < free), and checks that
         SNAPSHOT_ROOT is mounted with >= min_tb (or that a frozen subset is already present and read-only
         = a RED LINE placeholder; whether this bypass is accepted is not decided here); if official_manifests
         is given, the real-byte gate is added.
      2. real_byte_gate: required = real remote bytes (sum of each entity's root meta.content_length) x safety_margin vs free.
      3. pre_shard_space_ok: before writing each derived shard, remaining space < min_free -> False (treated as a permanent HALT, not transient).
  - Only returns a verdict, never sys.exit (the exit belongs to the U0 preflight thin shell / the calling script, which
    exits on CAPACITY_GATE_FAIL=16).

Neutral about identification choices: pure local decisions plus injected byte counts; real disk reads
(shutil.disk_usage/statvfs) are supplied by the operations script, so tests can inject them.
RED LINE placeholder (never decided here): whether the "frozen subset present + read-only" bypass can replace a >= min_tb
  physical disk; the values of est_derived/min_tb/spill_budget come from config (cfg fields), and this module has no built-in default thresholds.
Official usage: the snapshot bucket (full works compressed ~639GB, uncompressed ~1.6TB, needs an external disk);
  the top-level manifest.json carries meta.content_length (all entities) + entities[].content_length (per entity).
"""
from __future__ import annotations

from typing import Any, Mapping

# C-E: the capacity gate reuses U0 preflight's pure verdict disk_gate_decision (not manifest.capacity_preflight).
from common import preflight as _u0_preflight

# C-F: DATA_ROOT is consolidated to U0's single source of truth (derived tables go to <DATA_ROOT>/u1_fetch/). Not redefined in U1.
DATA_ROOT: str = _u0_preflight.DATA_ROOT

# Byte conversion (for GB reporting; 1 GiB = 1024^3).
_BYTES_PER_GB: int = 1024 ** 3
_BYTES_PER_TB: int = 1024 ** 4


# =============================================================================
# Real remote-byte gate — uses the official manifest's root meta.content_length (no estimates)
# =============================================================================

def remote_bytes_from_manifests(official_manifests: Mapping[str, Mapping[str, Any]]) -> int:
    """Sum of the root meta.content_length of each entity's official manifest = real remote total bytes.

    Argument official_manifests: {entity: manifest_view}, each manifest_view shaped like
        {"meta": {"content_length": <int>, "record_count": <int>}, ...}
      (= that entity's view returned by M0-1 fetch_official_manifest(entity); entities[i] of the top-level
       manifest.json split out has this shape, and the root meta.content_length = the entity's total compressed bytes).

    A missing meta or content_length -> raise an error naming the missing key (never silently count as 0 bytes, or the capacity gate would falsely pass).
    """
    total = 0
    for entity, manifest in official_manifests.items():
        meta = manifest.get("meta")
        if not isinstance(meta, Mapping) or "content_length" not in meta:
            raise ValueError(
                f"remote_bytes_from_manifests: the manifest of entity {entity!r} lacks "
                f"meta.content_length — refusing to silently count it as 0 bytes (the capacity gate must not go falsely green)"
            )
        total += int(meta["content_length"])
    return total


def real_byte_gate(
    official_manifests: Mapping[str, Mapping[str, Any]],
    *,
    snapshot_root_free_bytes: int,
    safety_margin: float = 1.15,
) -> dict[str, Any]:
    """Real-byte gate: required = remote real bytes x safety_margin, compared with SNAPSHOT_ROOT free space.

    snapshot_root_free_bytes: remaining bytes on the SNAPSHOT_ROOT volume (read by the thin shell with shutil.disk_usage; injected in tests).
    safety_margin: allowance for decompression/temporary growth (default 1.15; a numeric convention, not a red line; cfg can override it).
    Returns {ok, remote_gb, free_gb, required_gb}: required <= free -> ok=True.
    """
    remote_bytes = remote_bytes_from_manifests(official_manifests)
    required_bytes = remote_bytes * safety_margin
    return {
        "ok": required_bytes <= snapshot_root_free_bytes,
        "remote_gb": remote_bytes / _BYTES_PER_GB,
        "free_gb": snapshot_root_free_bytes / _BYTES_PER_GB,
        "required_gb": required_bytes / _BYTES_PER_GB,
    }


# =============================================================================
# Capacity gate before fetching (aggregate) — derived-size gate + mount/min_tb + optional real-byte gate; returns a verdict, never exits
# =============================================================================

def snapshot_capacity_gate(
    cfg: Mapping[str, Any],
    *,
    official_manifests: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Hard capacity gate before fetching: aggregates several checks; if any check fails -> passed=False (listed in fails). Never sys.exit.

    cfg fields (supplied by config/paths.yaml + runtime; numeric thresholds are not built into this module):
      - snapshot_root_mounted: bool       whether the SNAPSHOT_ROOT volume is mounted.
      - snapshot_root_free_bytes: int      remaining bytes on SNAPSHOT_ROOT (used by the real-byte gate and the derived-size gate).
      - snapshot_root_total_bytes: int     (optional) total bytes of the SNAPSHOT_ROOT volume, to test >= min_tb;
                                           if missing, free_bytes is used as an approximation (note: conservative).
      - snapshot_root_min_tb: float        lower bound on disk capacity (RED LINE placeholder; the "frozen subset + read-only" bypass is undecided).
      - est_derived_bytes: int             estimated bytes of the derived economics tables (given by config, not guessed here).
      - tmp_used_bytes: int                bytes already used in /tmp (counted in the need if on the same disk).
      - same_physical_disk: bool           whether data_root / /tmp / peak spill are on the same physical disk.

    Checks:
      A. mounted: snapshot_root_mounted must be True.
      B. min_tb: disk capacity (total, else free) >= the min_tb threshold.
      C. derived_disk: U0 preflight.disk_gate_decision (derived need < free).
      D. real_byte: when official_manifests is given, add real_byte_gate (remote bytes x margin <= free).

    Returns {passed, fails, arms}: fails use stable names (mounted/min_tb/derived_disk/real_byte_gate).
    """
    fails: list[str] = []
    arms: dict[str, Any] = {}

    free_bytes = int(cfg["snapshot_root_free_bytes"])

    # Check A: mounted.
    mounted = bool(cfg.get("snapshot_root_mounted", False))
    arms["snapshot_root_mounted"] = mounted
    if not mounted:
        fails.append("snapshot_root_mounted")

    # Check B: >= min_tb (disk-capacity gate; the RED LINE bypass is undecided — this only compares numbers and does not decide whether the bypass applies).
    min_tb = float(cfg["snapshot_root_min_tb"])
    total_bytes = int(cfg.get("snapshot_root_total_bytes", free_bytes))  # If total is missing, fall back to free (conservative)
    min_tb_ok = total_bytes >= min_tb * _BYTES_PER_TB
    arms["snapshot_root_min_tb"] = {
        "ok": min_tb_ok,
        "total_tb": total_bytes / _BYTES_PER_TB,
        "min_tb": min_tb,
    }
    if not min_tb_ok:
        fails.append("snapshot_root_min_tb")

    # Check C: derived-size disk gate — reuses U0 preflight.disk_gate_decision (passes only if need < free).
    #   derived need = est_derived (economics narrow tables) + peak spill (included in est_derived here, estimated by config);
    #   /tmp counts if on the same disk. Bytes are never estimated here; everything comes from cfg.
    est_derived_bytes = int(cfg["est_derived_bytes"])
    tmp_used_bytes = int(cfg.get("tmp_used_bytes", 0))
    same_disk = bool(cfg.get("same_physical_disk", True))
    derived_ok = _u0_preflight.disk_gate_decision(
        peak_spill_bytes=est_derived_bytes,
        data_root_used_bytes=0,           # The derived disk starts empty; space already used is counted separately by du in the operations script
        tmp_used_bytes=tmp_used_bytes,
        free_bytes=free_bytes,
        same_physical_disk=same_disk,
    )
    arms["derived_disk"] = derived_ok
    if not derived_ok:
        fails.append("derived_disk")

    # Check D: real-byte gate (added only when a manifest is given).
    if official_manifests is not None:
        rb = real_byte_gate(
            official_manifests,
            snapshot_root_free_bytes=free_bytes,
            safety_margin=float(cfg.get("safety_margin", 1.15)),
        )
        arms["real_byte_gate"] = rb
        if not rb["ok"]:
            fails.append("real_byte_gate")

    return {"passed": len(fails) == 0, "fails": fails, "arms": arms}


# =============================================================================
# Per-shard space gate — check remaining space before writing a derived shard (permanent HALT, not transient)
# =============================================================================

def pre_shard_space_ok(
    data_root: str,
    *,
    min_free_gb: float,
    free_gb: float,
) -> bool:
    """Check remaining space before writing each derived shard: free_gb < min_free_gb -> False (HALT).

    data_root: root of the derived disk (for records/diagnostics only; the real free space is injected via free_gb).
    free_gb: current free GB on that disk (read by the thin shell with shutil.disk_usage(data_root).free/GB; injected in tests).
    min_free_gb: the floor (given by config). Remaining space below the floor -> False = permanent HALT
                 (a full disk is structural, retrying will not help, so it is not requeued as transient).
    """
    return free_gb >= min_free_gb
