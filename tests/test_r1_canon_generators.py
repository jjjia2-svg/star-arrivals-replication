# -*- coding: utf-8 -*-
"""R1 P3 F7 (W1-CANON): the paper generators under the canon switch, end to end (big host, legacy).

1. test_default_root_outputs_byte_equal_to_pre_f7_code - the switch-off proof. The paper stage of
   analysis/run_all.sh (every generator in its order, the sentinel excluded) runs in a detached git
   worktree at the sha in tests/r1_paper_base.txt (the r1-code commit just before W1-CANON's red
   commit) and again at HEAD, both at the SAME directory so that absolute paths written into a
   provenance string are equal too, with the default paths config, SOURCE_DATE_EPOCH=0 and
   PYTHONHASHSEED=0. Every output/paper file and every exit code must be equal byte for byte. If the
   base sha is not in this clone (`git cat-file -e` fails) the test FAILS - it never skips. The one
   exception is SINCE_BASE: a file a later planned item changed on purpose, compared by its own exact
   rule (never skipped; a declared change that does not appear fails too).
2. test_october_copy_as_m_canon_gives_the_same_numbers - tools/r1_canon.py copy-october puts October
   into an out-of-repo M canon (CANON.json, prefix MANIFESTs); the same stage read through a paths
   yaml selecting it gives every non-underscore JSON value equal, every .tex/.csv byte-equal, and
   _provenance equal after mapping the October roots onto the canon prefixes.
3. test_reads_equal_canon_reads_tsv - in that M run every Python generator runs under an audit hook
   ('open') plus a DuckDB wrapper that records every canon path its SQL names: the files each one
   reads under the canon roots are exactly its analysis/lib/canon_reads.tsv rows (MANIFESTs and
   CANON.json excluded), and every row is read.

Needs the legacy tree mounted (run_all's paper stage reads it), Rscript with the pinned R stack, and
git history in the clone. ~3 paper stages; runs only in the big-host mode (pytestmark legacy).
"""
from __future__ import annotations

import fnmatch
import importlib.util
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

import pytest

pytestmark = pytest.mark.legacy

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from analysis.lib import canon  # noqa: E402

BASE_FILE = REPO / "tests" / "r1_paper_base.txt"
TIMEOUT = 3 * 3600
#: generators whose clean exit the comparison needs: if one fails at the base, nothing is proven
MUST_PASS = ("paper_ledger_p3afar", "paper_ledger_main", "paper_ledger_carried", "paper_ledger_funnel",
             "paper_fig_origins", "paper_ledger_p1p2", "paper_ledger_rob")

HARNESS = r'''
import json, os, re, runpy, sys
out, gen, args = sys.argv[1], sys.argv[2], sys.argv[3:]
ROOTS = [r.rstrip("/") for r in json.loads(os.environ["SAR_CANON_AUDIT_ROOTS"])]
seen = set()
def _note(s):
    if isinstance(s, (bytes, bytearray)):
        s = os.fsdecode(bytes(s))
    if isinstance(s, os.PathLike):
        s = os.fspath(s)
    if isinstance(s, (list, tuple, set)):
        for x in s: _note(x)
        return
    if isinstance(s, dict):
        for x in s.values(): _note(x)
        return
    if not isinstance(s, str):
        return
    for r in ROOTS:
        for m in re.finditer(re.escape(r) + r"/[^'\"\s,)\]]+", s):
            seen.add(m.group(0))
def _hook(event, a):
    if event == "open" and a and a[0] is not None and not isinstance(a[0], int):
        try:
            _note(os.path.abspath(os.fsdecode(a[0])))
        except (TypeError, ValueError):
            pass
sys.addaudithook(_hook)
try:
    import duckdb
    _WRAP = ("execute", "executemany", "sql", "query", "read_csv", "read_parquet", "read_json",
             "from_csv_auto", "from_parquet")
    class _Con:
        def __init__(self, c): object.__setattr__(self, "_c", c)
        def __getattr__(self, n):
            a = getattr(self._c, n)
            if n not in _WRAP:
                return a
            def w(*args, **kw):
                _note(list(args)); _note(kw)
                r = a(*args, **kw)
                return self if r is self._c else r
            return w
        def __enter__(self): self._c.__enter__(); return self
        def __exit__(self, *e): return self._c.__exit__(*e)
    _connect = duckdb.connect
    duckdb.connect = lambda *a, **k: _Con(_connect(*a, **k))
    for _n in ("sql", "query", "read_csv", "read_parquet"):
        if hasattr(duckdb, _n):
            def _mk(f):
                def w(*args, **kw):
                    _note(list(args)); _note(kw)
                    return f(*args, **kw)
                return w
            setattr(duckdb, _n, _mk(getattr(duckdb, _n)))
except ImportError:
    pass
code = 0
try:
    sys.argv = [gen] + args
    runpy.run_path(gen, run_name="__main__")
except SystemExit as e:
    code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
finally:
    with open(out, "w") as fh:
        json.dump({"reads": sorted(seen), "code": code}, fh)
sys.exit(code)
'''


def _git(*args, check=True):
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True, check=check)


def paper_stage() -> list[tuple[str, list[str]]]:
    """run_all.sh's paper stage at HEAD: [(name, argv with $PY/$PP expanded)], the sentinel excluded."""
    text = (REPO / "analysis" / "run_all.sh").read_text(encoding="utf-8")
    body = text.split('echo "== paper =="', 1)[1]
    out = []
    for ln in body.splitlines():
        m = re.match(r"^run (paper_\w+)\s+(.*?)\s*(#.*)?$", ln.strip())
        if not m or m.group(1) == "paper_check":
            continue
        argv = [tok.replace('"$PY"', sys.executable).replace("$PP", "analysis/paper") for tok in m.group(2).split()]
        out.append((m.group(1), argv))
    assert [n for n, _ in out][:2] == ["paper_ledger_p3afar", "paper_tables_p3afar"], out
    return out


def _env(paths_cfg=None, audit_roots=None) -> dict:
    env = {**os.environ, "SOURCE_DATE_EPOCH": "0", "PYTHONHASHSEED": "0", "MPLBACKEND": "Agg"}
    if paths_cfg is not None:
        env["SAR_PATHS_CONFIG"] = str(paths_cfg)
    if audit_roots is not None:
        env["SAR_CANON_AUDIT_ROOTS"] = json.dumps([str(r) for r in audit_roots])
    return env


def _tree_config(tree: pathlib.Path):
    """The default config for `tree`: $SAR_PATHS_CONFIG re-pointed at the tree's own copy when it
    names a file of this clone (relative values then resolve against the tree), else unchanged."""
    cur = os.environ.get("SAR_PATHS_CONFIG", "").strip()
    if not cur:
        return None
    p = pathlib.Path(cur).resolve()
    try:
        rel = p.relative_to(REPO.resolve())
    except ValueError:
        return p
    return tree / rel if (tree / rel).is_file() else p


def run_stage(tree: pathlib.Path, env: dict, audit_dir: pathlib.Path | None = None) -> dict:
    """Run the paper stage in `tree`; {name: {"code": rc, "reads": [...] (audited runs only)}}."""
    res = {}
    (tree / "output" / "logs").mkdir(parents=True, exist_ok=True)
    for name, argv in paper_stage():
        if audit_dir is not None and argv[0] == sys.executable:
            rec = audit_dir / f"{name}.json"
            cmd = [sys.executable, str(audit_dir / "harness.py"), str(rec), argv[1], *argv[2:]]
        else:
            rec, cmd = None, argv
        r = subprocess.run(cmd, cwd=tree, env=env, capture_output=True, text=True, timeout=TIMEOUT)
        (tree / "output" / "logs" / f"{name}.log").write_text(r.stdout + r.stderr)
        res[name] = {"code": r.returncode, "log": (r.stdout + r.stderr)[-3000:]}
        if rec is not None and rec.is_file():
            res[name].update(json.loads(rec.read_text()))
    return res


def _prepare(tree: pathlib.Path) -> None:
    """The git-ignored inputs a fresh worktree lacks: the cal intermediates (pairs_unified.csv) and
    the renv project library, taken from this clone."""
    src = REPO / "output" / "cal_intermediates"
    if src.is_dir():
        shutil.copytree(src, tree / "output" / "cal_intermediates", dirs_exist_ok=True)
    lib = REPO / "renv" / "library"
    if lib.is_dir() and not (tree / "renv" / "library").exists():
        (tree / "renv" / "library").symlink_to(lib, target_is_directory=True)


def _snapshot(tree: pathlib.Path, dest: pathlib.Path) -> pathlib.Path:
    src = tree / "output" / "paper"
    shutil.copytree(src, dest) if src.is_dir() else dest.mkdir()
    return dest


def _worktree(path: pathlib.Path, sha: str) -> None:
    if path.exists():
        _git("worktree", "remove", "--force", str(path), check=False)
        shutil.rmtree(path, ignore_errors=True)
    _git("worktree", "add", "--detach", str(path), sha)
    _prepare(path)


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("canon_gen")
    tree = tmp / "tree"                       # one directory for every run: equal absolute paths
    out = {"tmp": tmp, "tree": tree, "base_error": None}
    head = _git("rev-parse", "HEAD").stdout.strip()
    base = BASE_FILE.read_text(encoding="utf-8").split()[0]
    try:
        if _git("cat-file", "-e", f"{base}^{{commit}}", check=False).returncode != 0:
            out["base_error"] = (f"the pre-F7 base {base} (tests/r1_paper_base.txt) is not in this clone; "
                                 "fetch it - the byte proof cannot be skipped")
        else:
            _worktree(tree, base)
            out["base"] = run_stage(tree, _env(_tree_config(tree)))
            out["base_paper"] = _snapshot(tree, tmp / "base_paper")
        _worktree(tree, head)
        out["head"] = run_stage(tree, _env(_tree_config(tree)))
        out["head_paper"] = _snapshot(tree, tmp / "head_paper")

        shutil.rmtree(tree / "output" / "paper", ignore_errors=True)
        canon_root = tmp / "canon_m"
        m_cfg = tmp / "paths_m.yaml"
        # W2-N12P: ledger_p3afar reads canon.switch("p_full_precision"), and an undeclared switch is a CanonError;
        # the October copy declares it off, so the M run must give October's numbers (W2-INT)
        r = subprocess.run([sys.executable, "tools/r1_canon.py", "copy-october", str(canon_root),
                            "--switch", "p_full_precision=false",
                            "--paths-out", str(m_cfg)], cwd=tree, env=_env(_tree_config(tree)),
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr
        r = subprocess.run([sys.executable, "tools/r1_canon.py", "check", str(canon_root)], cwd=tree,
                           env=_env(), capture_output=True, text=True)
        assert r.returncode == 0 and "CANON_OK" in r.stdout, r.stdout + r.stderr
        audit = tmp / "audit"; audit.mkdir()
        (audit / "harness.py").write_text(HARNESS)
        out["canon"] = canon_root
        out["m"] = run_stage(tree, _env(m_cfg, [(canon_root / k).resolve() for k in canon.KEYS]), audit_dir=audit)
        out["m_paper"] = _snapshot(tree, tmp / "m_paper")
        yield out
    finally:
        _git("worktree", "remove", "--force", str(tree), check=False)
        _git("worktree", "prune", check=False)


def _files(d: pathlib.Path) -> dict:
    return {p.relative_to(d).as_posix(): p for p in sorted(d.rglob("*")) if p.is_file()}


#: N10's note claim (W1-PTABLES 45577fc): the claim text draft_2026_09_13_tables.robustness_table registers
N10_SHUFFLE = ("shuffling: ", "the only cell with fewer completed runs than requested")


def _n10_note_checks(base: bytes, head: bytes) -> str | None:
    """None when HEAD's NOTE_CHECKS.json is the base's list plus exactly one N10 shuffling claim that holds
    (the bytes of every other entry, and of the file around them, equal to the base); else what differs.

    Why the file changed after b6c4e71: N10 (W1-PTABLES, 45577fc) turned draft_2026_09_13_tables.py's hard
    `assert list(short) == ["p2_math_stats"]` (the note's "477 completed for mathematics, Panel 2" is the one
    cell with fewer completed shuffle runs) into a note claim, so it is a FLAG instead of a crash in M. In
    October it holds (the base's assert passed, or the base would have written no NOTE_CHECKS.json). Final
    review #16 (FINAL-FIX-STAGE 30819aa) made gate 2 collect this list and send a false claim to the author,
    so the claim must stay in it, and the no-flag run keeps writing the file exactly as the base did."""
    a, b = json.loads(base), json.loads(head)
    is_n10 = lambda c: (isinstance(c, dict) and c.get("table") == "tab:robustness"   # noqa: E731
                        and str(c.get("claim", "")).startswith(N10_SHUFFLE[0])
                        and str(c.get("claim", "")).endswith(N10_SHUFFLE[1]))
    if any(is_n10(c) for c in a):
        return "the base already registers the N10 shuffling claim; nothing is declared to have changed"
    new = [i for i, c in enumerate(b) if is_n10(c)]
    if len(new) != 1:
        return f"HEAD registers {len(new)} N10 shuffling claims, not exactly one"
    if b[new[0]].get("holds") is not True:
        return f"the N10 claim does not hold on the October ledgers: {b[new[0]]}"
    rest = b[:new[0]] + b[new[0] + 1:]
    if (json.dumps(rest, indent=1) + "\n").encode() != base:
        return "the entries other than the N10 claim differ from the base"
    return None


#: output/paper files a later planned item changed on purpose after the pre-F7 base (F7 itself changes no
#: October byte), each with its exact comparison; the rule names what differs, None when it is the declared change
SINCE_BASE = {"draft_2026_09_13/NOTE_CHECKS.json": _n10_note_checks}


def test_default_root_outputs_byte_equal_to_pre_f7_code(runs):
    assert runs["base_error"] is None, runs["base_error"]
    base, head = runs["base"], runs["head"]
    failed = {n: base[n]["log"] for n in MUST_PASS if base[n]["code"] != 0}
    assert not failed, f"generators fail at the base, so equality proves nothing: {failed}"
    assert {n: r["code"] for n, r in head.items()} == {n: r["code"] for n, r in base.items()}
    a, b = _files(runs["base_paper"]), _files(runs["head_paper"])
    assert a and set(a) == set(b), (sorted(set(a) ^ set(b)))
    missing = sorted(set(SINCE_BASE) - set(a))
    assert not missing, f"declared changed files the stage no longer writes: {missing}"
    diff = [k for k in a if k not in SINCE_BASE and a[k].read_bytes() != b[k].read_bytes()]
    assert not diff, f"output/paper files differ from the pre-F7 code: {diff}"
    declared = {k: why for k, rule in SINCE_BASE.items()
                if (why := rule(a[k].read_bytes(), b[k].read_bytes())) is not None}
    assert not declared, f"declared changes since the pre-F7 base are not what was declared: {declared}"


def _prefix_map(tree: pathlib.Path, root: pathlib.Path) -> list[tuple[str, str]]:
    pairs = [(str((tree / canon.OCTOBER[k]).resolve()), str((root / k).resolve())) for k in canon.KEYS]
    pairs += [(canon.OCTOBER[k] + "/", k + "/") for k in canon.KEYS]
    return sorted(pairs, key=lambda p: -len(p[0]))


def _mapped(x, pairs):
    if isinstance(x, str):
        for a, b in pairs:
            x = x.replace(a, b)
        return x
    if isinstance(x, list):
        return [_mapped(v, pairs) for v in x]
    if isinstance(x, dict):
        return {k: _mapped(v, pairs) for k, v in x.items()}
    return x


#: final review #4: the one _provenance difference an M canon may show. ledger_carried's star-stock
#: cross-check against the 08-28 layered stocks runs in the October canon only, so in M the provenance
#: drops exactly this clause (every value stays equal).
M_PROVENANCE_DROPS = {("data_numbers_carried.json", "chem_star_stock"): " (equal to the 08-28 layered stocks)",
                      ("data_numbers_carried.json", "math_star_stock"): " (equal to the 08-28 layered stocks)"}


def test_october_copy_as_m_canon_gives_the_same_numbers(runs):
    head, m = runs["head"], runs["m"]
    assert {n: r["code"] for n, r in m.items()} == {n: r["code"] for n, r in head.items()}, \
        {n: m[n]["log"] for n in m if m[n]["code"] != head[n]["code"]}
    a, b = _files(runs["head_paper"]), _files(runs["m_paper"])
    assert set(a) == set(b), sorted(set(a) ^ set(b))
    pairs = _prefix_map(runs["tree"], runs["canon"])
    probs = []
    for k in a:
        if k.endswith((".tex", ".csv")):
            if a[k].read_bytes() != b[k].read_bytes():
                probs.append(f"{k}: bytes differ")
        elif k.endswith(".json"):
            ja, jb = json.loads(a[k].read_text()), json.loads(b[k].read_text())
            if not isinstance(ja, dict):
                probs += [] if ja == jb else [f"{k}: value differs"]
                continue
            for key in sorted(set(ja) | set(jb)):
                if key.startswith("_") and key != "_provenance":
                    continue
                want = _mapped(ja.get(key), pairs) if key == "_provenance" else ja.get(key)
                if key == "_provenance" and isinstance(want, dict):
                    for (fname, pk), clause in M_PROVENANCE_DROPS.items():
                        if fname == k and pk in want:
                            if clause not in want[pk]:
                                probs.append(f"{k}: October _provenance.{pk} lacks the October-only clause {clause!r}")
                            want[pk] = want[pk].replace(clause, "")
                if want != jb.get(key):
                    probs.append(f"{k}: {key} differs")
    assert not probs, probs


def _csv_rows(p: pathlib.Path):
    import csv
    with open(p, newline="", encoding="utf-8") as fh:
        rd = csv.DictReader(fh)
        return list(rd.fieldnames or []), list(rd)


def _csv_write(p: pathlib.Path, fields, rows) -> None:
    import csv
    with open(p, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def test_m_canon_new_chem_event_and_changed_stock_pass_ledger_carried(tmp_path):
    """final review #4. In M the chem/math star stocks are the M restake's (RK6b own-field / C pass
    after_stock; 60 chemistry and 79 mathematics ACCEPTs are new stars with no 08-28 stock), so the
    October-only cross-check against the 08-28 layered stocks must not run there. An M canon copied
    from October, with one new chemistry event (and its restake row) and one changed after_stock: the
    generator exits 0 and chem_star_stock is computed from the modified M stocks (n = 38 + 1). Before
    the fix it stops with 'October restake stock differs from the 08-28 layered stock' (the legacy tree
    is mounted here, as on the final host)."""
    import duckdb
    root, m_cfg, out = tmp_path / "canon_m", tmp_path / "paths_m.yaml", tmp_path / "out"
    r = subprocess.run([sys.executable, "tools/r1_canon.py", "copy-october", str(root),
                        "--paths-out", str(m_cfg), "--output", str(out)],
                       cwd=REPO, env=_env(), capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    cal = root / "cal"
    ev_p = cal / "events_chemistry_cal2026-10.csv"
    rs_p = cal / "_invalid_run2" / "restake_2026-10.csv"
    ev_f, ev = _csv_rows(ev_p)
    rs_f, rs = _csv_rows(rs_p)
    assert len(ev) == 38, len(ev)
    new = dict(ev[0], author_id="A_R1_FINAL_TEST_NEW")
    ev.append(new)
    evset = [(e["author_id"], int(float(e["arrival_corrected"]))) for e in ev]
    chem = [x for x in rs if x["field"] == "chemistry"]
    changed = next(x for x in chem if (x["author_id"], int(float(x["arrival_true"]))) in evset)
    changed["after_stock"] = str(int(float(changed["after_stock"])) + 1)
    top = max(int(float(x["after_stock"])) for x in chem) + 1000
    rs.append(dict(changed, author_id=new["author_id"], arrival_true=new["arrival_corrected"],
                   after_stock=str(top)))
    _csv_write(ev_p, ev_f, ev)
    _csv_write(rs_p, rs_f, rs)
    r = subprocess.run([sys.executable, "tools/r1_canon.py", "manifest", str(root)],
                       cwd=REPO, env=_env(), capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr

    r = subprocess.run([sys.executable, "analysis/paper/ledger_carried.py"], cwd=REPO, env=_env(m_cfg),
                       capture_output=True, text=True, timeout=TIMEOUT)
    assert r.returncode == 0, (r.stdout + r.stderr)[-3000:]
    got = json.loads((out / "paper" / "data_numbers_carried.json").read_text(encoding="utf-8"))

    stocks = {(x["author_id"], int(float(x["arrival_true"]))): int(float(x["after_stock"]))
              for x in rs if x["field"] == "chemistry"}
    vals = [stocks[k] for k in evset]
    q25, med, q75 = duckdb.connect().execute(
        "SELECT quantile_disc(x,[0.25,0.5,0.75]) FROM (SELECT unnest($1::BIGINT[]) x)", [vals]).fetchone()[0]
    assert got["chem_star_stock"] == {"q25": int(q25), "med": int(med), "q75": int(q75), "max": top, "n": 39}
    prov = got["_provenance"]["chem_star_stock"]
    assert prov == "cal/_invalid_run2/restake_2026-10.csv after_stock (chem/math rows, valid), " \
                   "events_chemistry_cal2026-10.csv", prov



def _dup_first_row(con, pq: pathlib.Path) -> None:
    """Rewrite a roster parquet with its first row repeated: one more spell, the same people."""
    tmp = pq.with_suffix(".tmp.parquet")
    con.execute(f"COPY (SELECT * FROM parquet_scan('{pq}') UNION ALL (SELECT * FROM parquet_scan('{pq}') LIMIT 1)) "
                f"TO '{tmp}' (FORMAT parquet)")
    tmp.replace(pq)


def test_m_canon_r1_roster_shapes_pass_ledger_carried(tmp_path):
    """M audit (ledger_carried, final-03 follow-up). An M canon copied from October, given R1's roster shapes:
    the added-roster sheet becomes a spell table with no evidence column, one econ person gets a second spell
    (the econ build report's roster pool counts rows), and one chemistry person gets a second spell (so the
    2026-08-10 prep_final_report no longer counts the chemistry roster). The generator exits 0; the two econ
    evidence keys and chem_centre_added are listed in _unreproducible, never derived; math_centre_added, whose
    roster still matches, is kept; roster_people counts people, not rows. Before the fix it stops at the
    roster-pool rows check: the 88 October rows are rewritten into the spell form, so the 88-row assert passes;
    the evidence branch is chosen by the sheet's header, not by its row count."""
    import hashlib
    import duckdb
    root, m_cfg, out = tmp_path / "canon_m", tmp_path / "paths_m.yaml", tmp_path / "out"
    r = subprocess.run([sys.executable, "tools/r1_canon.py", "copy-october", str(root),
                        "--paths-out", str(m_cfg), "--output", str(out)],
                       cwd=REPO, env=_env(), capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    cal, raw = root / "cal", root / "raw_verified"
    con = duckdb.connect()

    def sha(p):
        return hashlib.sha256(p.read_bytes()).hexdigest()

    added = cal / "roster_added_2026-10.csv"
    _f, rows = _csv_rows(added)
    spell = ["dept_key", "author_id", "year_start", "year_end", "year_source"]
    _csv_write(added, spell, [{**{k: x[k] for k in spell[:4]}, "year_source": "list"} for x in rows])

    econ_pq = cal / "roster_econ_verified_2026-10.parquet"
    _dup_first_row(con, econ_pq)
    n_rows, n_people = con.execute(f"SELECT count(*), count(DISTINCT author_id) FROM parquet_scan('{econ_pq}')").fetchone()
    assert n_rows == n_people + 1
    rep_p = cal / "frames_econ" / "build_report_econ920_2026-10.json"
    rep = json.loads(rep_p.read_text(encoding="utf-8"))
    rep["october"]["regeneration"]["roster_pool"].update(source_sha256=sha(econ_pq), rows_in=n_rows)
    rep_p.write_text(json.dumps(rep, indent=1), encoding="utf-8")

    chem_pq = raw / "roster_gold_chemistry.parquet"
    _dup_first_row(con, chem_pq)
    rep_p = cal / "frames_chemistry" / "build_report_chemistry.json"
    rep = json.loads(rep_p.read_text(encoding="utf-8"))
    rep["october"]["inpost"]["spells"]["roster_sha256"] = sha(chem_pq)
    rep_p.write_text(json.dumps(rep, indent=1), encoding="utf-8")
    r = subprocess.run([sys.executable, "tools/r1_canon.py", "manifest", str(root)],
                       cwd=REPO, env=_env(), capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr

    r = subprocess.run([sys.executable, "analysis/paper/ledger_carried.py"], cwd=REPO, env=_env(m_cfg),
                       capture_output=True, text=True, timeout=TIMEOUT)
    assert r.returncode == 0, (r.stdout + r.stderr)[-3000:]
    got = json.loads((out / "paper" / "data_numbers_carried.json").read_text(encoding="utf-8"))
    unrep = got.get("_unreproducible") or {}
    gone = {"econ_arc_evidence_people", "econ_fellow_evidence_rows", "chem_centre_added"}
    assert set(unrep) == gone, unrep
    assert not gone & set(got) and not gone & set(got["_provenance"])
    assert all(isinstance(v, str) and v.strip() for v in unrep.values())
    assert "134" not in unrep["chem_centre_added"]
    assert got["math_centre_added"] == 28                      # the mathematics roster still matches its report
    assert got["roster_people"]["econ"] == n_people and got["roster_people"]["chem"] == 518
    assert "unchanged in October" not in got["_provenance"]["roster_people"]
    # no pin of config/r1/M.json has this roster's bytes, so no no-centre roster is named
    assert "pins no no-research-centre roster" in unrep["chem_centre_added"], unrep["chem_centre_added"]


@pytest.mark.skipif(not (REPO / "data/cal2026-10r1/inputs/rosters").is_dir(),
                    reason="R1 roster sources are not shipped")
def test_m_canon_r1_rosters_name_what_the_no_centre_rosters_give(tmp_path):
    """M audit, review 0 (final-03 follow-up, round 2). An M canon copied from October with R1's chemistry and
    mathematics rosters (the files config/r1/M.json pins). prep_final_report (2026-08-10) counts other rosters,
    so both centre keys stay in _unreproducible (whether the footnote prints the M number is the author's call),
    and each reason says what the rosters in force give: the people of the full roster less those of the
    no-research-centre roster pinned beside it (roster_gold_<f>_r1_incfel.parquet), read from the files. Before
    the fix the reason says no source in force marks the centre entries."""
    import hashlib
    import duckdb
    root, m_cfg, out = tmp_path / "canon_m", tmp_path / "paths_m.yaml", tmp_path / "out"
    r = subprocess.run([sys.executable, "tools/r1_canon.py", "copy-october", str(root),
                        "--paths-out", str(m_cfg), "--output", str(out)],
                       cwd=REPO, env=_env(), capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    cal, raw = root / "cal", root / "raw_verified"
    rosters = REPO / "data" / "cal2026-10r1" / "inputs" / "rosters"  # private sources, not shipped
    con = duckdb.connect()
    want = {}
    for d, f in (("chem", "chemistry"), ("math", "math_stats")):
        full, nc = rosters / f"roster_gold_{f}_r1.parquet", rosters / f"roster_gold_{f}_r1_incfel.parquet"
        pq = raw / f"roster_gold_{f}.parquet"
        pq.unlink()
        pq.write_bytes(full.read_bytes())
        rep_p = cal / f"frames_{f}" / f"build_report_{f}.json"
        rep = json.loads(rep_p.read_text(encoding="utf-8"))
        rep["october"]["inpost"]["spells"]["roster_sha256"] = hashlib.sha256(pq.read_bytes()).hexdigest()
        rep_p.write_text(json.dumps(rep, indent=1), encoding="utf-8")
        people, spells = con.execute(f"SELECT count(DISTINCT author_id), count(*) FROM parquet_scan('{full}')").fetchone()
        n_nc = con.execute(f"SELECT count(DISTINCT author_id) FROM parquet_scan('{nc}')").fetchone()[0]
        left = con.execute(f"SELECT count(DISTINCT author_id) FROM parquet_scan('{full}') WHERE author_id NOT IN "
                           f"(SELECT author_id FROM parquet_scan('{nc}'))").fetchone()[0]
        want[d] = (people, spells, n_nc, left, nc.relative_to(REPO).as_posix())
    r = subprocess.run([sys.executable, "tools/r1_canon.py", "manifest", str(root)],
                       cwd=REPO, env=_env(), capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr

    r = subprocess.run([sys.executable, "analysis/paper/ledger_carried.py"], cwd=REPO, env=_env(m_cfg),
                       capture_output=True, text=True, timeout=TIMEOUT)
    assert r.returncode == 0, (r.stdout + r.stderr)[-3000:]
    got = json.loads((out / "paper" / "data_numbers_carried.json").read_text(encoding="utf-8"))
    unrep = got.get("_unreproducible") or {}
    assert {"chem_centre_added", "math_centre_added"} <= set(unrep), unrep
    assert "chem_centre_added" not in got and "math_centre_added" not in got
    for d, (people, spells, n_nc, left, nc_key) in want.items():
        why = unrep[f"{d}_centre_added"]
        assert f"{people:,} people, {spells:,} spells" in why and f"{nc_key}: {n_nc:,} people" in why, why
        assert f"leaves out {left:,} of those {people:,} people" in why, why
        assert "author's call" in why and "no source in force" not in why, why
    assert got["roster_people"]["chem"] == want["chem"][0] and got["roster_people"]["math"] == want["math"][0]

def test_reads_equal_canon_reads_tsv(runs):
    spec = importlib.util.spec_from_file_location("r1_canon_tool", REPO / "tools" / "r1_canon.py")
    tool = importlib.util.module_from_spec(spec); spec.loader.exec_module(tool)   # type: ignore[union-attr]
    rows = [r for r in tool.read_tsv() if r["key"] in canon.KEYS]
    root = runs["canon"]
    probs = []
    for name, argv in paper_stage():
        if argv[0] != sys.executable:
            continue                                   # R scripts: not audited (paths.R only)
        gen = pathlib.Path(argv[1]).name
        got = runs["m"][name]
        assert "reads" in got, f"{name}: no audit record ({got['log']})"
        reads = set()
        for s in got["reads"]:
            p = pathlib.Path(s)
            if p.name.endswith("MANIFEST.sha256") or p.name == canon.CANON_JSON:
                continue
            k = next(k for k in canon.KEYS if (root / k).resolve() in p.resolve().parents)
            reads.add((k, p.resolve().relative_to((root / k).resolve()).as_posix()))
        mine = [r for r in rows if r["generator"] == gen]
        unlisted = sorted(f"{k}/{rel}" for k, rel in reads
                          if not any(r["key"] == k and fnmatch.fnmatchcase(rel, r["rel"]) for r in mine))
        unread = sorted(f"{r['key']}/{r['rel']}" for r in mine
                        if not any(r["key"] == k and fnmatch.fnmatchcase(rel, r["rel"]) for k, rel in reads))
        if unlisted:
            probs.append(f"{gen} reads files canon_reads.tsv does not list: {unlisted}")
        if unread:
            probs.append(f"{gen} has canon_reads.tsv rows it never read: {unread}")
    assert not probs, "\n".join(probs)
