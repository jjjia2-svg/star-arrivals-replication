# -*- coding: utf-8 -*-
"""pipeline/aws/r1/rk6_requests.py - RK6 inputs from the merged table, and the RK6a summary."""
from __future__ import annotations

import csv
import hashlib
import json
import pathlib
import sys

import pandas as pd
import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "pipeline" / "aws" / "r1"))
import rk6_requests as rq   # noqa: E402

COLS = ["person_id", "all_ids", "name", "field", "school", "department", "arrival_year", "status",
        "status_reason", "resolve_rule", "sources", "n_records", "years_seen", "conflict", "no_id",
        "needs_rank", "returning_alumnus", "question", "prior_pct_11", "prior_pct_source"]


def _row(pid, field, year, status, sources, ids=None):
    return {"person_id": pid, "all_ids": ids or pid, "name": f"N {pid}", "field": field, "school": "x",
            "arrival_year": year, "status": status, "status_reason": "r", "sources": sources}


def _merged(tmp_path, rows):
    p = tmp_path / "candidates_merged.csv"
    with open(p, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in COLS})
    return p


def _recovered(base, fails=(), manifest_sha=None):
    rec = base / "recovered"
    (rec / "rk1" / "payload" / "in").mkdir(parents=True)
    (rec / "rk4" / "payload" / "in").mkdir(parents=True)
    text = "print('rk1')\n"
    (rec / "rk1" / "payload" / "rk1.py").write_text(text)
    sha = manifest_sha or hashlib.sha256(text.encode()).hexdigest()
    (rec / "manifest.tsv").write_text(f"run\tpart\tmember\tbytes\tsha256\nrk1\tpayload\trk1.py\t{len(text)}\t{sha}\n")
    (rec / "checks.json").write_text(json.dumps({"fails": list(fails)}))
    (rec / "RESULT.txt").write_text("OK\n" if not fails else "RECOVERY_FAIL\n")
    for name, body in (("drops.csv", "aid,wid\nA1000001,W1\n"), ("adds.csv", "aid,wid\n"), ("control.json", "[]\n")):
        (rec / "rk1" / "payload" / "in" / name).write_text(body)
    (rec / "rk4" / "payload" / "in" / "requests.json").write_text(json.dumps([
        {"key": "k", "ids": ["A2000002"], "Y": 2009, "field": "econ", "exclude_wids": ["W77"], "min_year": 1990, "cleaning": True}]))
    return rec


def test_build_ranks_every_g0_person_and_every_open_candidate(tmp_path):
    merged = _merged(tmp_path, [
        _row("A1000001", "econ", 2010, "rank", "G0"),
        _row("A1000002", "econ", 2008, "out", "G0"),                      # a signed drop is still ranked (flip list)
        _row("A2000002", "econ", 2010, "rank", "G1"),
        _row("A2000003", "chemistry", 2015, "rule_pending", "S_rul"),
        _row("A2000004", "math_stats", 2016, "insufficient", "G6"),       # not ranked
        _row("A2000005", "math_stats", "", "rank", "G1"),                 # no year: not ranked
        _row("A2000006", "econ", 2023, "rank", "G0", ids="A2000006|A2000007")])
    rec = _recovered(tmp_path)
    assert rq.main(["build", "--merged", str(merged), "--recovered", str(rec), "--out", str(tmp_path / "in6")]) == 0
    by = {q["person"]: q for q in json.loads((tmp_path / "in6" / "requests.json").read_text())}
    assert set(by) == {"A1000001", "A1000002", "A2000002", "A2000003", "A2000006"}
    assert by["A1000001"]["Y"] == 2009 and by["A1000001"]["key"] == "econ|A1000001|Y2009"
    assert by["A2000002"]["exclude_wids"] == ["W77"] and by["A2000002"]["min_year"] == 1990 and by["A2000002"]["prior_cleaning"]
    assert by["A2000006"]["ids"] == ["A2000006", "A2000007"] and by["A2000006"]["cleaning"]
    for name in ("drops.csv", "adds.csv", "control.json"):
        assert (tmp_path / "in6" / name).read_bytes() == (rec / "rk1" / "payload" / "in" / name).read_bytes()
    assert "requests.json" in json.loads((tmp_path / "in6" / "inputs.json").read_text())


def test_build_refuses_a_failed_recovery_or_a_changed_rk1(tmp_path):
    merged = _merged(tmp_path, [_row("A1000001", "econ", 2010, "rank", "G0")])
    with pytest.raises(SystemExit, match="recovery"):
        rq.main(["build", "--merged", str(merged), "--recovered", str(_recovered(tmp_path / "a", fails=["x"])),
                 "--out", str(tmp_path / "o1")])
    with pytest.raises(SystemExit, match="rk1.py"):
        rq.main(["build", "--merged", str(merged), "--recovered", str(_recovered(tmp_path / "b", manifest_sha="0" * 64)),
                 "--out", str(tmp_path / "o2")])


def test_build_refuses_s3_copies_that_differ_from_the_git_pins(tmp_path):
    merged = _merged(tmp_path, [_row("A1000001", "econ", 2010, "rank", "G0")])
    rec = _recovered(tmp_path)
    pins = tmp_path / "pins.json"
    good = {"rk1/payload/rk1.py": hashlib.sha256(b"print('rk1')\n").hexdigest(), "manifest.tsv": rq.sha256(rec / "manifest.tsv")}
    pins.write_text(json.dumps(good))
    assert rq.main(["build", "--merged", str(merged), "--recovered", str(rec), "--out", str(tmp_path / "o1"),
                    "--pins", str(pins)]) == 0
    pins.write_text(json.dumps(dict(good, **{"manifest.tsv": "0" * 64})))
    with pytest.raises(SystemExit, match="pins"):
        rq.main(["build", "--merged", str(merged), "--recovered", str(rec), "--out", str(tmp_path / "o2"), "--pins", str(pins)])


def test_build_refuses_an_rk6a_run_that_did_not_pass(tmp_path):
    merged = _merged(tmp_path, [_row("A1000001", "econ", 2010, "rank", "G0")])
    rk6a = tmp_path / "rk6a"
    rk6a.mkdir()
    (rk6a / "RESULT.txt").write_text("CONTROL_FAIL\n")
    fs = tmp_path / "out" / "summary.json"
    with pytest.raises(SystemExit, match="RK6a did not pass"):
        rq.main(["build", "--merged", str(merged), "--recovered", str(_recovered(tmp_path)), "--out", str(tmp_path / "o"),
                 "--rk6a-out", str(rk6a), "--fail-summary", str(fs)])
    assert json.loads(fs.read_text())["result"] == "BUILD_FAIL" and (fs.parent / "RESULT.txt").read_text() == "BUILD_FAIL\n"


CTRL = [{"author_id": "A9000001", "field": "econ", "arrival_true": 2010, "ext": "11", "expected_pct": 0.9512},
        {"author_id": "A9000002", "field": "econ", "arrival_true": 2012, "ext": "11", "expected_pct": None},
        {"author_id": "A9000003", "field": "chemistry", "arrival_true": 2008, "ext": "0705", "expected_pct": 0.9301}]
RANK_COLS = ["key", "author_id", "field", "arrival_true", "Y", "stock", "cell", "cell_n", "aage", "pct", "pass_p10", "note", "ext", "pass"]


def _write_ranks(p, rows):
    with open(p, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(RANK_COLS)
        w.writerows(rows)


def _rk_out(tmp_path, result="OK", drop_control=None):
    out = tmp_path / "rkout"
    out.mkdir()
    (out / "RESULT.txt").write_text(result + "\n")
    (out / "rk1_report.json").write_text(json.dumps({"control_fail": [] if result == "OK" else [["x"]], "secs": 1}))
    rows = [["econ|A1000001|Y2009", "A1000001", "econ", "2010", "2009", "900", "2002|6-9", "500", "7", "0.95", "True", "", "11", "A"],
            ["econ|A2000002|Y2009", "A2000002", "econ", "2010", "2009", "100", "2002|6-9", "500", "7", "0.5", "False", "", "11", "A"],
            ["CONTROL|A9000001", "A9000001", "econ", "2010", "2009", "800", "2002|6-9", "500", "9", "0.95121", "True", "", "11", "A"],
            ["CONTROL|A9000002", "A9000002", "econ", "2012", "2011", "", "", "", "", "", "False", "not_in_pool", "11", "A"]]
    ctrl0705 = [["CONTROL|A9000003", "A9000003", "chemistry", "2008", "2007", "700", "1605|6-9", "80", "8", "0.9301", "True", "", "0705", "A"]]
    _write_ranks(out / "ranks_11_A.csv", [r for r in rows if r[1] != drop_control])
    _write_ranks(out / "ranks_0705_A.csv", [r for r in ctrl0705 if r[1] != drop_control])
    pd.DataFrame({"aid": ["A2000002", "A2000002", "A1000001", "A5008470795"], "wid": ["W1", "W2", "W3", "W4"],
                  "yr": [2005, 2012, 2001, 2003], "c": [10, 5, 3, 1], "sf": ["2002"] * 4,
                  "title": ["a", "b", "c", "d"]}).to_parquet(out / "works_11.parquet")
    return out


def _requests(inp):
    inp.mkdir()
    (inp / "requests.json").write_text(json.dumps([
        {"key": "econ|A1000001|Y2009", "person": "A1000001", "ids": ["A1000001"], "Y": 2009, "field": "econ", "status": "rank", "src": "G0", "prior_cleaning": False},
        {"key": "econ|A2000002|Y2009", "person": "A2000002", "ids": ["A2000002"], "Y": 2009, "field": "econ", "status": "rank", "src": "G1", "prior_cleaning": False},
        {"key": "econ|A2000003|Y2009", "person": "A2000003", "ids": ["A2000003"], "Y": 2009, "field": "econ", "status": "rank", "src": "G1", "prior_cleaning": True},
        {"key": "econ|A5008470795|Y2010", "person": "A5008470795", "ids": ["A5008470795"], "Y": 2010, "field": "econ", "status": "rank", "src": "G0", "prior_cleaning": False}]))
    (inp / "control.json").write_text(json.dumps(CTRL))
    return inp


def test_summarize_counts_and_writes_the_review_pack(tmp_path):
    merged = _merged(tmp_path, [_row("A1000001", "econ", 2010, "rank", "G0"), _row("A2000002", "econ", 2010, "rank", "G1"),
                                _row("A2000003", "econ", 2010, "rank", "G1"), _row("A5008470795", "econ", 2011, "rank", "G0")])
    inp = _requests(tmp_path / "in6")
    out = _rk_out(tmp_path)
    assert rq.main(["summarize", "--rk-out", str(out), "--in", str(inp), "--merged", str(merged)]) == 0
    s = json.loads((out / "summary.json").read_text())
    assert s["result"] == "OK" and s["control_fail"] == 0 and s["requests"] == 4
    assert s["control_rows"] == {"0705": 1, "11": 2} and s["control_gaps"] == 0 and s["control_empty"] == 1
    assert s["counts"]["econ|rank|G0"] == {"requests": 2, "pass_unfiltered": 1, "not_in_pool": 0}
    need = [n["person_id"] for n in json.loads((out / "review_pack" / "needs_check.json").read_text())]
    assert need == ["A2000002", "A5008470795"]          # G0 skipped except A5008470795; the cleaned one skipped
    assert (out / "review_pack" / "needs_check_ids.txt").read_text() == "A2000002\nA5008470795\n"
    works = json.loads((out / "review_pack" / "works" / "A2000002.json").read_text())
    assert [w["wid"] for w in works["works"]] == ["W1"]   # works up to Y only
    assert "N A2000002" not in (out / "summary.json").read_text()


def test_summarize_fails_when_the_control_failed(tmp_path):
    merged = _merged(tmp_path, [_row("A1000001", "econ", 2010, "rank", "G0")])
    inp = _requests(tmp_path / "in6")
    out = _rk_out(tmp_path, result="CONTROL_FAIL")
    assert rq.main(["summarize", "--rk-out", str(out), "--in", str(inp), "--merged", str(merged)]) == 1


def test_summarize_recounts_the_control_and_fails_on_a_missing_row(tmp_path):
    """rk1.py checks the CONTROL rows it wrote, never their number."""
    merged = _merged(tmp_path, [_row("A1000001", "econ", 2010, "rank", "G0")])
    inp = _requests(tmp_path / "in6")
    out = _rk_out(tmp_path, drop_control="A9000003")
    assert rq.main(["summarize", "--rk-out", str(out), "--in", str(inp), "--merged", str(merged)]) == 1
    assert (out / "RESULT.txt").read_text().strip() == "CONTROL_FAIL"
    assert json.loads((out / "summary.json").read_text())["control_gaps"] == 1


R1 = {"schema": "sar.r1.paper_read.v1", "person_id": "A2000002", "id_ok": True, "correct_ids": [], "merge_ids": [],
      "exclude_wids": ["W1", "W2"], "uncertain_wids": [], "first_pub_year": 1999, "summary": "s",
      "sources": ["https://example.org/a"], "agent": "reader-1"}
R2 = {"schema": "sar.r1.paper_check2.v1", "person_id": "A2000002", "verdict": "changed", "id_ok": True, "correct_ids": [],
      "wrongly_excluded_wids": ["W2"], "missed_wids": ["W3"], "merge_ids_add": [], "merge_ids_drop": [], "note": "n",
      "sources": ["https://example.org/b"], "agent": "checker-1"}


def _pack(base, pid, wids):
    d = base / "rk6a" / "review_pack" / "works"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{pid}.json").write_text(json.dumps({"person_id": pid, "ids": [pid], "Y": 2009, "works": [{"wid": w} for w in wids]}))
    return d


def _checks(base, pid, r1, r2):
    root = base / "paper_checks"
    for rnd, body in (("round1", r1), ("round2", r2)):
        (root / rnd).mkdir(parents=True, exist_ok=True)
        if body is not None:
            (root / rnd / f"{pid}.json").write_text(json.dumps(body))
    return root


def test_paper_checks_merge_the_two_rounds(tmp_path):
    works = _pack(tmp_path, "A2000002", ["W1", "W2", "W3"])
    got = rq.load_paper_checks(_checks(tmp_path, "A2000002", R1, R2), works)
    assert got["A2000002"] == {"exclude_wids": ["W1", "W3"], "merge_ids": [], "id_ok": True, "correct_ids": []}


def test_paper_checks_refuse_a_missing_round_or_an_unknown_work(tmp_path):
    works = _pack(tmp_path, "A2000002", ["W1"])
    with pytest.raises(SystemExit, match="round2"):
        rq.load_paper_checks(_checks(tmp_path / "a", "A2000002", R1, None), works)
    with pytest.raises(SystemExit, match="not in the person's list"):
        rq.load_paper_checks(_checks(tmp_path / "b", "A2000002", R1, R2), works)


def test_an_id_dispute_leaves_the_person_unranked(tmp_path):
    works = _pack(tmp_path, "A2000002", ["W1", "W2", "W3"])
    got = rq.load_paper_checks(_checks(tmp_path, "A2000002", R1, dict(R2, id_ok=False)), works)
    assert got["A2000002"]["id_ok"] is False and got["A2000002"]["correct_ids"] == []
    reqs, skipped = rq.requests_from_merged([_row("A2000002", "econ", 2010, "rank", "G1")], {}, got)
    assert reqs == [] and skipped == ["A2000002"]


EXTRA = {"schema": "sar.r1.paper_extra.v1", "person_id": "A2000002", "profile_ids": ["A2000009"], "merge_ids": ["A2000009"],
         "exclude_wids": ["W90", "W91"], "decided": "2026-10-11: fix the profile first, then rerun RK6b", "note": "n",
         "sources": ["https://example.org/c"], "agent": "extra-1"}


def _extra(root, pid, body):
    (root / "extra").mkdir(parents=True, exist_ok=True)
    (root / "extra" / f"{pid}.json").write_text(json.dumps(body))


def test_extra_file_excludes_works_on_a_merged_profile(tmp_path):
    """Works on a merged or corrected profile are not in the RK6a works list; an extra file names the ones someone
    else wrote, and its merge ids join the rounds' (2026-10-11, before RK6b)."""
    works = _pack(tmp_path, "A2000002", ["W1", "W2", "W3"])
    root = _checks(tmp_path, "A2000002", R1, R2)
    _extra(root, "A2000002", EXTRA)
    got = rq.load_paper_checks(root, works)["A2000002"]
    assert got["exclude_wids"] == ["W1", "W3", "W90", "W91"] and got["merge_ids"] == ["A2000009"]


def test_extra_file_may_name_the_corrected_id_profile(tmp_path):
    works = _pack(tmp_path, "A2000002", ["W1", "W2", "W3"])
    root = _checks(tmp_path, "A2000002", dict(R1, id_ok=False), dict(R2, id_ok=False, correct_ids=["A2000009"]))
    _extra(root, "A2000002", dict(EXTRA, merge_ids=[]))
    got = rq.load_paper_checks(root, works)["A2000002"]
    assert got["correct_ids"] == ["A2000009"] and "W90" in got["exclude_wids"] and got["merge_ids"] == []


def test_extra_file_is_refused_when_malformed_orphaned_or_unanchored(tmp_path):
    works = _pack(tmp_path, "A2000002", ["W1", "W2", "W3"])
    cases = [(dict(EXTRA, schema="x"), "extra.*schema"),
             (dict(EXTRA, decided=""), "extra.*decided"),
             (dict(EXTRA, exclude_wids=["X9"]), "extra.*malformed"),
             (dict(EXTRA, merge_ids=[]), "extra.*profile"),        # neither merged nor the corrected id
             (dict(EXTRA, person_id="A2000003"), "extra.*person_id")]
    for n, (body, msg) in enumerate(cases):
        root = _checks(tmp_path / str(n), "A2000002", R1, R2)
        _extra(root, "A2000002", body)
        with pytest.raises(SystemExit, match=msg):
            rq.load_paper_checks(root, works)
    root = _checks(tmp_path / "orphan", "A2000002", R1, R2)
    _extra(root, "A2000004", dict(EXTRA, person_id="A2000004"))
    with pytest.raises(SystemExit, match="extra.*round1"):
        rq.load_paper_checks(root, works)


def test_extra_file_drops_a_round_merge_a_later_check_found_is_someone_else(tmp_path):
    """J0-MEAS.3e (A5008470795, 2026-10-16): round 1 merged a profile that a later two-round check found holds another
    person's works. merge_ids_drop in the extra file takes it out of the merge ids, as round 2's merge_ids_drop
    does, so none of its works (before or after Y) reach the ranking or the dose; its exclusions still apply."""
    works = _pack(tmp_path, "A2000002", ["W1", "W2", "W3"])
    root = _checks(tmp_path, "A2000002", dict(R1, merge_ids=["A2000008"]), R2)
    _extra(root, "A2000002", dict(EXTRA, merge_ids_drop=["A2000008"], exclude_wids=["W90", "W95"]))
    got = rq.load_paper_checks(root, works)["A2000002"]
    assert got["merge_ids"] == ["A2000009"] and got["exclude_wids"] == ["W1", "W3", "W90", "W95"]
    reqs, _ = rq.requests_from_merged([_row("A2000002", "econ", 2010, "rank", "G1")], {}, {"A2000002": got})
    assert reqs[0]["ids"] == ["A2000002", "A2000009"]


def test_extra_file_drop_is_refused_unless_only_the_rounds_merged_the_id(tmp_path):
    works = _pack(tmp_path, "A2000002", ["W1", "W2", "W3"])
    merged8 = dict(R1, merge_ids=["A2000008"])
    cases = [(R1, dict(EXTRA, merge_ids_drop=["A2000008"]), "extra.*merge_ids_drop"),                 # never merged
             (dict(R1, merge_ids=["A2000009"]), dict(EXTRA, merge_ids_drop=["A2000009"]), "extra.*merge_ids_drop"),  # and merged here
             (merged8, dict(EXTRA, merge_ids_drop=["A2000008"], profile_ids=["A2000008"]), "extra.*profile"),  # dropped, not covered
             (merged8, dict(EXTRA, merge_ids_drop=["X8"]), "extra.*malformed")]
    for n, (r1, body, msg) in enumerate(cases):
        root = _checks(tmp_path / str(n), "A2000002", r1, R2)
        _extra(root, "A2000002", body)
        with pytest.raises(SystemExit, match=msg):
            rq.load_paper_checks(root, works)
