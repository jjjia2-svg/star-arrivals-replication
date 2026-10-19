"""The R1 run config (P3c F9): one schema, one loader, and a STOP instead of a guess.

Every R1 stage and wrapper reads its switches, rulings and October constants through this module, from
the JSON file `$SAR_R1_CONFIG` names (config/r1/B0.json = October, config/r1/M.json = the new run).
Loading STOPs with `ConfigStop(code, detail)` on:

    UNSET            $SAR_R1_CONFIG is not set (never a default - same rule as $SAR_PATHS_CONFIG)
    BAD_SCHEMA       not a sar.r1.run_config.v1 file for B0 or M, or a malformed counts file
    UNSIGNED         a ruling without value, decided or source; a switch row without decided
                     (B0 rows are decided exactly 'B0: October (tag cal-2026-10)')
    MISSING_RULING   a REQUIRED_RULINGS id is absent
    MISMATCH_SIGNED  a ruling that says something other than the signed files (p2_decisions.json
                     c_rulings by normalised id, rulings_p1.json own_field, flips_r1.json for h8/h9)
    UNKNOWN_SWITCH   a switch row the registry does not hold (name, value, owner) or a duplicate
    MISSING_SWITCH   a registry switch without a row
    B0_SWITCH_ON     a B0 switch away from its off value
    ADD_LIST_NOT_OK  M while add_list_r1_summary.json does not say 'OK' (today: ROSTER_GAP)
    UNDECIDED_ROW    M with a flips or add-list row without 'decided' or with a verdict outside
                     {KEEP, DROP} / {ACCEPT, REJECT}
    BAD_PATH         an absolute path, '..', an unknown token, or a work: token off an R1 host
    MISSING_INPUT    a declared input or pinned file is absent
    PIN_MISMATCH     a pinned file whose sha256 differs, or a signed file that is not pinned

Paths in a config are tokens: 'repo:<rel>' resolves against the repo, 'work:<rel>' against $WORK and
only on an R1 instance ($SAR_HOST ec2-r1 / ec2-r1-test). Any other string is returned raw (labels).

The switch registry is FROZEN after wave 1. This file sits on the B0 chain: editing it forces a J0
rerun (gates.py link). A later item that builds a switch's code edits only its own consumer.

    from pipeline.lib import r1_config
    cfg = r1_config.load_env()
    stage_cfg = cfg.resolved("stage")          # October's constants for stage.py / econ920_lib
    if cfg.is_on("network_freeze"): ...
    n_econ = r1_config.counts()["events"]["econ"]

Standard library only; reads the config and the signed lists, never a data table.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

SCHEMA = "sar.r1.run_config.v1"
COUNTS_SCHEMA = "sar.r1.counts.v1"
CONFIG_ENV = "SAR_R1_CONFIG"
COUNTS_ENV = "SAR_R1_COUNTS"
COUNTS_B0 = "config/r1/counts_B0.json"
HOSTS = ("ec2-r1-test", "ec2-r1")
NAMES = ("B0", "M")
B0_DECIDED = "B0: October (tag cal-2026-10)"
FIELDS = ("econ", "chemistry", "math_stats")

CODES = ("UNSET", "BAD_SCHEMA", "UNSIGNED", "MISSING_RULING", "MISMATCH_SIGNED", "UNKNOWN_SWITCH",
         "MISSING_SWITCH", "B0_SWITCH_ON", "ADD_LIST_NOT_OK", "UNDECIDED_ROW", "BAD_PATH", "MISSING_INPUT",
         "PIN_MISMATCH")

#: name -> B0 (October) value, M value, the item that owns its consumer. FROZEN after wave 1.
SWITCHES: dict[str, dict[str, str]] = {
    "verdict_source": {"off": "october", "on": "signed", "owner": "F16/F17/F10"},
    "own_field_rank": {"off": "off", "on": "field_topic", "owner": "V3-RANK"},
    "label_fix": {"off": "off", "on": "pass_C", "owner": "V3-RANK/F17"},
    "p05_label_fix": {"off": "off", "on": "pctC_0.95_celln_30", "owner": "F17"},
    "network_freeze": {"off": "off", "on": "both_hops_le_T-1", "owner": "V3-NET"},
    "chemmath_edges": {"off": "u1_edges_full_2026-07-05", "on": "u1_full_11school_2026-07-16", "owner": "N2"},
    "new_stars": {"off": "off", "on": "add_list_r1", "owner": "F10"},
    "redates": {"off": "off", "on": "signed", "owner": "F10/F11"},
    "calls": {"off": "october", "on": "r1", "owner": "F8"},
    "dose_excludes": {"off": "off", "on": "not_this_person", "owner": "F8/F13/F14"},
    "dose_mode": {"off": "october", "on": "delta", "owner": "F13/F14"},
    "add_backs": {"off": "off", "on": "on", "owner": "F13/F14"},
    "rosters": {"off": "october", "on": "r1", "owner": "P3a/F11/F14"},
    "departure_ledger": {"off": "0910", "on": "r1", "owner": "F20"},
    "agg_missing": {"off": "report", "on": "stop", "owner": "N3"},
    "patch_raw": {"off": "none", "on": "r1", "owner": "F18"},
    "p_full_precision": {"off": "off", "on": "on", "owner": "N12"},
}

REQUIRED_RULINGS: tuple[str, ...] = (
    "h1", "h2", "h3", "h4", "h5", "h6", "h7", "h8", "h9", "h12", "h15",
    "C5", "C7", "C10", "C11", "C13", "F12", "M_rerun", "own_field", "label_fix",
    "decision_2", "decision_3", "decision_4", "decision_5", "gdose_override")

#: p2_decisions.json c_rulings stores short strings ('v3', 'mac (2026-10-11)', 'U+7532: ...' for option A).
#: Each id maps to (the normalised id the signed file must carry, the value the run config must carry -
#: the meaning of that P2 decision). Character equality with the signed string is not the test.
SIGNED_C: dict[str, tuple[str, str]] = {
    "C5": ("v3", "both hops <= T-1"),
    "C7": ("mac", "Mac fetch -> S3 r1/ -> AWS"),
    "C10": ("v3", "old79/new37 run in B0 only"),
    "C11": ("v3", "cap years as printed"),
    "C13": ("v3", "new-star departures screened"),
    "F12": ("no", "no"),
    "M_rerun": ("no", "no"),
    "label_fix": ("person-level", "pass_C"),
}
OWN_FIELD_RANK = "topic_field"
#: the signed P2 file (c_rulings own_field) labels this option with the CJK letter U+7532 ("option A")
SIGNED_OWN_FIELD_ID = "\u7532"
OWN_FIELD_CODES = {"econ": "20", "chemistry": "16", "math_stats": "26"}

#: h8 (A5008470795) and h9 (A5001177483) are superseded by the signed flips: both must be KEEP there.
FLIPS_VALUE = "superseded by flips_r1.json"
FLIPS_KEEP = {"h8": "A5008470795", "h9": "A5001177483"}

#: the signed lists a config names under "signed", per config. Every one must be pinned.
SIGNED_KEYS = {"B0": ("p2_decisions", "rulings_p1", "flips"),
               "M": ("p2_decisions", "rulings_p1", "flips", "add_list", "add_list_summary")}
VERDICTS = {"flips": {"KEEP", "DROP"}, "add_list": {"ACCEPT", "REJECT"}}

_TOKEN = re.compile(r"^([A-Za-z][\w+.-]*):(?!\s)")


class ConfigStop(RuntimeError):
    """A run config that must not be used. `code` is one of CODES; `detail` names ids and paths, never names."""

    def __init__(self, code: str, detail: str = ""):
        assert code in CODES, code
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code, self.detail = code, detail


# --- paths ----------------------------------------------------------------------------------------
def _check_rel(rel: str, where: str) -> str:
    if not rel or rel.startswith(("/", "~")) or ".." in rel.split("/") or "\\" in rel:
        raise ConfigStop("BAD_PATH", f"{where}: {rel!r} must be a relative path inside its root, without '..'")
    return rel


def _check_string(s: str, where: str) -> None:
    """A section string: a repo:/work: token with a clean relative part, or a raw label that is no path."""
    m = _TOKEN.match(s)
    if m:
        if m.group(1) not in ("repo", "work"):
            raise ConfigStop("BAD_PATH", f"{where}: unknown token {m.group(1)!r}: (only repo: and work:)")
        _check_rel(s[len(m.group(0)):], where)
    elif s.startswith(("/", "~")) or ".." in s.split("/"):
        raise ConfigStop("BAD_PATH", f"{where}: {s!r} is a bare path; write repo:<rel> or work:<rel>")


def _walk_strings(obj, where: str):
    if isinstance(obj, str):
        yield obj, where
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk_strings(v, f"{where}[{i}]")
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk_strings(v, f"{where}.{k}")


def _repo_token(tok, where: str) -> str:
    """The relative part of a 'repo:' token (inputs and signed lists live in the repo)."""
    if not isinstance(tok, str) or not tok.startswith("repo:"):
        raise ConfigStop("BAD_PATH", f"{where}: {tok!r} must be a repo:<rel> token")
    return _check_rel(tok[len("repo:"):], where)


def _work_root() -> pathlib.Path:
    host = os.environ.get("SAR_HOST", "").strip()
    if host not in HOSTS:
        raise ConfigStop("BAD_PATH", f"work: tokens resolve only on an R1 instance ($SAR_HOST in {HOSTS})")
    work = os.environ.get("WORK", "").strip()
    if not work or not os.path.isabs(work):
        raise ConfigStop("BAD_PATH", "work: tokens need $WORK, an absolute path")
    return pathlib.Path(work)


def _resolve(obj, repo: pathlib.Path):
    if isinstance(obj, str):
        if obj.startswith("repo:"):
            return repo / obj[len("repo:"):]
        if obj.startswith("work:"):
            return _work_root() / obj[len("work:"):]
        return obj
    if isinstance(obj, list):
        return [_resolve(v, repo) for v in obj]
    if isinstance(obj, dict):
        return {k: _resolve(v, repo) for k, v in obj.items()}
    return obj


def _sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_json(path: pathlib.Path, what: str):
    if not path.is_file():
        raise ConfigStop("MISSING_INPUT", f"{what}: {path} does not exist")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        raise ConfigStop("BAD_SCHEMA", f"{what}: {path} is not JSON ({e})") from None


def _norm_id(s) -> str:
    """'mac (2026-10-11)' -> 'mac'; 'U+7532: OpenAlex topic field' -> the letter U+7532; 'v3' -> 'v3'."""
    return re.split(r"[\s:：(（]", str(s).strip(), maxsplit=1)[0].lower()


def _filled(v) -> bool:
    if isinstance(v, str):
        return bool(v.strip())
    return v not in (None, {}, [])


# --- the config -----------------------------------------------------------------------------------
class RunConfig:
    """A loaded, checked run config. Read-only accessors; every miss is a ConfigStop."""

    def __init__(self, raw: dict, *, path: pathlib.Path, sha256: str, repo: pathlib.Path):
        self.raw, self.file, self.sha256, self.repo = raw, path, sha256, repo
        self.name: str = raw["config"]
        self._switches = {r["switch"]: r["value"] for r in raw["switches"]}
        self._rulings = {r["id"]: r for r in raw["rulings"]}

    def switch(self, name: str) -> str:
        if name not in SWITCHES:
            raise ConfigStop("UNKNOWN_SWITCH", f"{name!r} is not in the registry")
        return self._switches[name]

    def is_on(self, name: str) -> bool:
        return self.switch(name) != SWITCHES[name]["off"]

    def ruling(self, rid: str):
        if rid not in self._rulings:
            raise ConfigStop("MISSING_RULING", f"{rid!r} is not in {self.file.name}")
        return self._rulings[rid]["value"]

    def section(self, name: str) -> dict:
        sections = self.raw.get("sections") or {}
        if name not in sections:
            raise ConfigStop("BAD_SCHEMA", f"{self.file.name} has no section {name!r}")
        return json.loads(json.dumps(sections[name]))   # a copy: callers cannot edit the config

    def resolved(self, name: str) -> dict:
        """The section with repo:/work: tokens as Paths (lists and nested dicts too); other values raw."""
        return _resolve(self.section(name), self.repo)

    def path(self, section: str, key: str) -> pathlib.Path:
        sec = self.section(section)
        if key not in sec:
            raise ConfigStop("BAD_SCHEMA", f"section {section!r} has no key {key!r}")
        v = sec[key]
        if not isinstance(v, str) or not v.startswith(("repo:", "work:")):
            raise ConfigStop("BAD_PATH", f"{section}.{key} is not a repo:/work: token")
        return _resolve(v, self.repo)

    def data_ref(self, name: str) -> dict:
        refs = self.raw.get("data_refs") or {}
        if name not in refs:
            raise ConfigStop("MISSING_INPUT", f"{self.file.name} has no data_ref {name!r}")
        return json.loads(json.dumps(refs[name]))


def load(path, *, repo=REPO_ROOT) -> RunConfig:
    """Read and check a run config. A relative `path` is taken against `repo`."""
    repo = pathlib.Path(repo)
    path = pathlib.Path(path)
    if not path.is_absolute():
        path = repo / path
    raw = _read_json(path, "run config")
    _check_schema(raw, path)
    name = raw["config"]
    _check_paths(raw)
    _check_switches(raw, name)
    _check_rulings(raw)
    _check_inputs(raw, repo)
    signed = _check_pins(raw, name, repo)
    _check_signed(raw, signed)
    if name == "M":
        _check_m(signed)
    return RunConfig(raw, path=path, sha256=_sha256(path), repo=repo)


def load_env(*, repo=REPO_ROOT) -> RunConfig:
    """The config `$SAR_R1_CONFIG` names (absolute, or relative to the repo). Unset is a STOP."""
    value = os.environ.get(CONFIG_ENV, "").strip()
    if not value:
        raise ConfigStop("UNSET", f"${CONFIG_ENV} is not set; the stage cmd names the run config "
                                  f"(config/r1/B0.json or config/r1/M.json) - there is no default")
    return load(value, repo=repo)


def counts(path=None) -> dict:
    """The run's event counts: `path`, else $SAR_R1_COUNTS, else the committed config/r1/counts_B0.json."""
    if path is None:
        env = os.environ.get(COUNTS_ENV, "").strip()
        path = env or COUNTS_B0
    path = pathlib.Path(path)
    if not path.is_absolute():
        path = REPO_ROOT / path
    d = _read_json(path, "counts")
    ok = (isinstance(d, dict) and d.get("schema") == COUNTS_SCHEMA and d.get("config") in NAMES
          and isinstance(d.get("events"), dict) and all(isinstance(d["events"].get(f), int) for f in FIELDS)
          and isinstance(d.get("events_total"), int) and isinstance(d.get("candidates"), int)
          and d["events_total"] == sum(d["events"][f] for f in FIELDS))
    if not ok:
        raise ConfigStop("BAD_SCHEMA", f"{path} is not a {COUNTS_SCHEMA} file with events {FIELDS}, "
                                       f"events_total = their sum, and candidates")
    return d


# --- the checks, in load order --------------------------------------------------------------------
def _check_schema(raw, path) -> None:
    if not isinstance(raw, dict) or raw.get("schema") != SCHEMA:
        raise ConfigStop("BAD_SCHEMA", f"{path.name}: schema must be {SCHEMA}")
    if raw.get("config") not in NAMES:
        raise ConfigStop("BAD_SCHEMA", f"{path.name}: config must be one of {NAMES}")
    for key, typ in (("rulings", list), ("switches", list), ("pins", dict), ("signed", dict),
                     ("sections", dict), ("inputs", list)):
        if not isinstance(raw.get(key), typ):
            raise ConfigStop("BAD_SCHEMA", f"{path.name}: '{key}' must be a {typ.__name__}")
    for key in ("rulings", "switches"):
        if not all(isinstance(r, dict) for r in raw[key]):
            raise ConfigStop("BAD_SCHEMA", f"{path.name}: every '{key}' row is an object")


def _check_paths(raw) -> None:
    for s, where in _walk_strings(raw["sections"], "sections"):
        _check_string(s, where)
    for i, tok in enumerate(raw["inputs"]):
        _repo_token(tok, f"inputs[{i}]")
    for key, tok in raw["signed"].items():
        _repo_token(tok, f"signed.{key}")
    for rel in raw["pins"]:
        _check_rel(rel, "pins")


def _check_switches(raw, name) -> None:
    seen = set()
    for row in raw["switches"]:
        sw = row.get("switch")
        reg = SWITCHES.get(sw)
        if reg is None or sw in seen:
            raise ConfigStop("UNKNOWN_SWITCH", f"{sw!r} is {'a duplicate row' if sw in seen else 'not in the registry'}")
        seen.add(sw)
        if row.get("owner") != reg["owner"]:
            raise ConfigStop("UNKNOWN_SWITCH", f"{sw}: owner {row.get('owner')!r}, registry {reg['owner']!r}")
        if row.get("value") not in (reg["off"], reg["on"]):
            raise ConfigStop("UNKNOWN_SWITCH", f"{sw}: value {row.get('value')!r} is neither "
                                               f"{reg['off']!r} (off) nor {reg['on']!r} (on)")
        if not _filled(row.get("decided")):
            raise ConfigStop("UNSIGNED", f"switch {sw} has no 'decided'")
        if name == "B0":
            if row["value"] != reg["off"]:
                raise ConfigStop("B0_SWITCH_ON", f"{sw} = {row['value']!r}; B0 is October ({reg['off']!r})")
            if row["decided"] != B0_DECIDED:
                raise ConfigStop("UNSIGNED", f"B0 switch {sw} must be decided {B0_DECIDED!r}")
    missing = [sw for sw in SWITCHES if sw not in seen]
    if missing:
        raise ConfigStop("MISSING_SWITCH", ", ".join(missing))


def _check_rulings(raw) -> None:
    ids = [r.get("id") for r in raw["rulings"]]
    dup = sorted({i for i in ids if ids.count(i) > 1}, key=str)
    if dup:
        raise ConfigStop("BAD_SCHEMA", f"duplicate ruling ids {dup}")
    have = {r.get("id"): r for r in raw["rulings"]}
    missing = [rid for rid in REQUIRED_RULINGS if rid not in have]
    if missing:
        raise ConfigStop("MISSING_RULING", ", ".join(missing))
    for rid, r in have.items():
        empty = [k for k in ("value", "decided", "source") if not _filled(r.get(k))]
        if empty:
            raise ConfigStop("UNSIGNED", f"ruling {rid}: no {'/'.join(empty)}")


def _check_inputs(raw, repo) -> None:
    for tok in raw["inputs"]:
        p = repo / tok[len("repo:"):]
        if not p.exists():
            raise ConfigStop("MISSING_INPUT", tok)


def _check_pins(raw, name, repo) -> dict[str, pathlib.Path]:
    """Every pin matches; every signed list is pinned. Returns the signed lists as paths."""
    for rel, sha in raw["pins"].items():
        p = repo / rel
        if not p.is_file():
            raise ConfigStop("MISSING_INPUT", f"pinned {rel}")
        if _sha256(p) != sha:
            raise ConfigStop("PIN_MISMATCH", rel)
    signed = {}
    for key in SIGNED_KEYS[name]:
        if key not in raw["signed"]:
            raise ConfigStop("ADD_LIST_NOT_OK" if key == "add_list_summary" else "MISMATCH_SIGNED",
                             f"{name} must name the signed list {key!r}")
        rel = raw["signed"][key][len("repo:"):]
        if rel not in raw["pins"]:
            raise ConfigStop("PIN_MISMATCH", f"signed list {rel} is not pinned")
        signed[key] = repo / rel
    return signed


def _check_signed(raw, signed) -> None:
    rulings = {r["id"]: r for r in raw["rulings"]}
    c_rulings = _read_json(signed["p2_decisions"], "p2_decisions").get("c_rulings") or {}
    for rid, (norm, value) in SIGNED_C.items():
        if rid not in c_rulings or _norm_id(c_rulings[rid]) != norm:
            raise ConfigStop("MISMATCH_SIGNED", f"p2_decisions c_rulings {rid} is not {norm!r}")
        if rulings[rid]["value"] != value:
            raise ConfigStop("MISMATCH_SIGNED", f"{rid} = {rulings[rid]['value']!r}; signed {value!r}")

    own = rulings["own_field"]["value"]
    signed_own = (_read_json(signed["rulings_p1"], "rulings_p1").get("own_field") or {})
    if _norm_id(c_rulings.get("own_field", "")) != SIGNED_OWN_FIELD_ID:
        raise ConfigStop("MISMATCH_SIGNED", f"p2_decisions c_rulings own_field is not {SIGNED_OWN_FIELD_ID!r}")
    if not isinstance(own, dict) or own.get("rank") != OWN_FIELD_RANK:
        raise ConfigStop("MISMATCH_SIGNED", f"own_field rank must be {OWN_FIELD_RANK!r}")
    for key in ("scope", "age_basis"):
        if own.get(key) != signed_own.get(key):
            raise ConfigStop("MISMATCH_SIGNED", f"own_field {key} = {own.get(key)!r}; "
                                                f"rulings_p1 {signed_own.get(key)!r}")
    codes = {f: str(v) for f, v in (own.get("field_code") or {}).items()}
    signed_codes = {f: str(v) for f, v in (signed_own.get("field_code") or {}).items()}
    if not (codes == signed_codes == OWN_FIELD_CODES):
        raise ConfigStop("MISMATCH_SIGNED", f"own_field field codes {codes}; rulings_p1 {signed_codes}; "
                                            f"signed {OWN_FIELD_CODES}")

    flips = {r.get("person_id"): r for r in _read_json(signed["flips"], "flips").get("rows") or []}
    for rid, pid in FLIPS_KEEP.items():
        if rulings[rid]["value"] != FLIPS_VALUE:
            raise ConfigStop("MISMATCH_SIGNED", f"{rid} = {rulings[rid]['value']!r}; signed {FLIPS_VALUE!r}")
        if (flips.get(pid) or {}).get("verdict") != "KEEP":
            raise ConfigStop("MISMATCH_SIGNED", f"{rid}: flips row {pid} is not KEEP")


def _check_m(signed) -> None:
    summary = _read_json(signed["add_list_summary"], "add_list_summary")
    if not isinstance(summary, dict) or summary.get("result") != "OK":
        result = summary.get("result") if isinstance(summary, dict) else None
        gaps = len(summary.get("roster_gaps") or []) if isinstance(summary, dict) else 0
        raise ConfigStop("ADD_LIST_NOT_OK", f"add_list_r1_summary result {result!r} ({gaps} roster gaps); "
                                            f"M loads once the P3a rosters close them and the add list is rerun")
    for key, allowed in VERDICTS.items():
        rows = _read_json(signed[key], key).get("rows") or []
        if not rows:
            raise ConfigStop("UNDECIDED_ROW", f"{key}: no rows")
        for i, r in enumerate(rows):
            if not _filled(r.get("decided")) or r.get("verdict") not in allowed:
                raise ConfigStop("UNDECIDED_ROW", f"{key} row {i} ({r.get('person_id')}): verdict "
                                                  f"{r.get('verdict')!r} must be one of {sorted(allowed)} and decided")
