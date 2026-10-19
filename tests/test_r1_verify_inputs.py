# -*- coding: utf-8 -*-
"""pipeline/aws/r1/verify_inputs.py - folder manifests, pins, data and recovered checks (toy dirs, fake aws)."""
from __future__ import annotations

import hashlib
import json
import pathlib
import shutil
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "pipeline" / "aws" / "r1"))
sys.path.insert(0, str(REPO / "tests"))
import verify_inputs as vi                          # noqa: E402
from r1_fakes import install_fake_aws               # noqa: E402


@pytest.fixture(autouse=True)
def _host(monkeypatch):
    monkeypatch.setenv("SAR_HOST", "ec2-r1-test")


def _tree(root, files):
    for rel, body in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(body)
    return root


def test_manifest_is_order_free_and_names_every_file(tmp_path):
    a = _tree(tmp_path / "a", {"x/1.csv": b"1\n", "2.csv": b"22\n"})
    b = _tree(tmp_path / "b", {"2.csv": b"22\n", "x/1.csv": b"1\n"})
    ma, mb = vi.manifest_of_dir(a), vi.manifest_of_dir(b)
    assert ma["manifest_sha256"] == mb["manifest_sha256"] and (ma["files"], ma["bytes"]) == (2, 5)
    assert ma["text"] == "".join(f"{hashlib.sha256(c).hexdigest()}  {r}\n" for r, c in ((("2.csv"), b"22\n"), ("x/1.csv", b"1\n")))
    (b / "x" / "1.csv").write_bytes(b"9\n")
    assert vi.manifest_of_dir(b)["manifest_sha256"] != ma["manifest_sha256"]


def test_a_symlink_inside_a_pinned_folder_is_refused(tmp_path):
    a = _tree(tmp_path / "a", {"f": b"x"})
    (a / "link").symlink_to(a / "f")
    with pytest.raises(SystemExit, match="symlink"):
        vi.manifest_of_dir(a)


def _job(tmp_path, pairs):
    p = tmp_path / "job.json"
    p.write_text(json.dumps({"data_sync": pairs}))
    return p


def test_verify_data_names_a_changed_file_and_a_missing_pin(tmp_path):
    d = _tree(tmp_path / "data" / "derived", {"t/a.parquet": b"aa"})
    pins = tmp_path / "pins.json"
    pins.write_text(json.dumps({"schema": "sar.r1.input_pins.v1", "pins": {
        "r1/derived/": {k: vi.manifest_of_dir(d)[k] for k in ("files", "bytes", "manifest_sha256")}}}))
    out = tmp_path / "out"
    assert vi.main(["data", "--job-spec", str(_job(tmp_path, [["r1/derived/", f"{d}/"]])), "--pins", str(pins), "--out", str(out)]) == 0
    (d / "t" / "a.parquet").write_bytes(b"ab")
    assert vi.main(["data", "--job-spec", str(_job(tmp_path, [["r1/derived/", f"{d}/"]])), "--pins", str(pins), "--out", str(out)]) == 1
    assert json.loads((out / "verify_inputs.json").read_text())["r1/derived/"]["ok"] is False
    job = _job(tmp_path, [["u1_x/", f"{tmp_path}/data/u1_x/"]])
    (tmp_path / "data" / "u1_x").mkdir()
    assert vi.main(["data", "--job-spec", str(job), "--pins", str(pins), "--out", str(out)]) == 1


def test_verify_data_excludes_nested_sync_targets(tmp_path):
    base = _tree(tmp_path / "derived", {"r1only/a": b"1"})
    _tree(base / "u1_t", {"b": b"2"})
    pins = {"r1/derived/": vi.manifest_of_dir(tmp_path / "derived", exclude=[base / "u1_t"]),
            "u1_t/": vi.manifest_of_dir(base / "u1_t")}
    p = tmp_path / "pins.json"
    p.write_text(json.dumps({"pins": {k: {x: v[x] for x in ("files", "bytes", "manifest_sha256")} for k, v in pins.items()}}))
    job = _job(tmp_path, [["r1/derived/", f"{base}/"], ["u1_t/", f"{base}/u1_t/"]])
    assert vi.main(["data", "--job-spec", str(job), "--pins", str(p), "--out", str(tmp_path / "o")]) == 0
    assert pins["r1/derived/"]["files"] == 1


def test_pin_hashes_each_synced_prefix_without_writing_s3(tmp_path, monkeypatch):
    fake = install_fake_aws(tmp_path, monkeypatch)
    _tree(fake["s3root"] / "fake-bucket" / "r1" / "derived", {"t/a": b"1"})
    _tree(fake["s3root"] / "fake-bucket" / "u1_t", {"b": b"22"})
    _tree(fake["s3root"] / "fake-bucket" / "r1" / "ref" / "october", {"output_paper/x.json": b"{}"})   # JOB_EXTRA
    # every other always-synced pair the inventory tool declares (JOB_EXTRA grew in R1 wave 1: the legacy
    # v2_output root, the REF4 rank references, sub-tables, snapshot authors/institutions) gets one toy file,
    # because pin hashes each one and a prefix with nothing under it is a STOP
    sys.path.insert(0, str(REPO / "tools"))
    import r1_input_inventory as rii                  # noqa: PLC0415
    extra = {src for pairs in rii.JOB_EXTRA.values() for src, _dest in pairs}
    assert {"r1/ref/october/", "r1/legacy/legacy_v2_output/", "r1/runs/rk6b-06/out/files/"} <= extra
    for src in sorted(extra):
        _tree(fake["s3root"] / "fake-bucket" / src, {"toy.bin": src.encode("utf-8")})
    inv = tmp_path / "inv.tsv"
    inv.write_text("root\tname\tavailability\ts3_prefix\tinstance_path\tneeded_by\tused_by\n"
                   "derived\tt\ts3\tr1/derived/t/\t/data/openalex_pipeline/derived/t/\tj0\tx\n"
                   "derived\tu1_t\ts3\tu1_t/\t/data/openalex_pipeline/derived/u1_t/\tj0\tx\n")
    before = sorted(p for p in fake["s3root"].rglob("*"))
    out = tmp_path / "out"
    assert vi.main(["pin", "--bucket", "s3://fake-bucket", "--inventory", str(inv), "--repo", str(REPO),
                    "--work", str(tmp_path / "w"), "--out", str(out), "--job", "pin-unit"]) == 0
    s = json.loads((out / "summary.json").read_text())
    assert s["schema"] == "sar.r1.input_pins.v1" and set(s["pins"]) == {"r1/derived/", "u1_t/"} | extra
    assert s["pins"]["u1_t/"]["files"] == 1 and s["pins"]["r1/derived/"]["files"] == 1
    assert s["pins"]["r1/ref/october/"]["files"] == 2 and (out / "RESULT.txt").read_text().strip() == "OK"
    assert sorted(p for p in fake["s3root"].rglob("*")) == before


def test_recovered_checks_every_manifest_member_and_the_git_pin(tmp_path):
    rec = _tree(tmp_path / "rec", {"rk1/payload/rk1.py": b"print(1)\n", "rk4/payload/requests.json": b"{}\n"})
    rows = [("rk1", "payload", "rk1.py"), ("rk4", "payload", "requests.json")]
    man = "run\tpart\tmember\tbytes\tsha256\n" + "".join(
        f"{r}\t{p}\t{m}\t{(rec / r / p / m).stat().st_size}\t{hashlib.sha256((rec / r / p / m).read_bytes()).hexdigest()}\n" for r, p, m in rows)
    (rec / "manifest.tsv").write_text(man)
    pins = tmp_path / "pins.json"
    pins.write_text(json.dumps({"manifest.tsv": hashlib.sha256(man.encode()).hexdigest()}))
    assert vi.main(["recovered", "--dir", str(rec), "--pins", str(pins)]) == 0
    (rec / "rk4" / "payload" / "requests.json").write_bytes(b"{ }\n")
    assert vi.main(["recovered", "--dir", str(rec), "--pins", str(pins)]) == 1


def test_refuses_off_aws(monkeypatch, tmp_path):
    monkeypatch.delenv("SAR_HOST")
    with pytest.raises(SystemExit, match="R1 instance"):
        vi.main(["recovered", "--dir", str(tmp_path), "--pins", str(tmp_path / "p.json")])


def test_recovered_reads_launch_side_rows_where_recover_rk_wrote_them(tmp_path):
    """recover_rk.manifest_rows() records launch-side files as run 'kit', part 'launch_side'; on disk they sit
    at <dir>/launch_side/<member> (recovered_pins key 'launch_side/prep_rk1.py')."""
    rec = _tree(tmp_path / "rec", {"launch_side/prep_rk1.py": b"x = 1\n"})
    body = (rec / "launch_side" / "prep_rk1.py").read_bytes()
    man = f"run\tpart\tmember\tbytes\tsha256\nkit\tlaunch_side\tprep_rk1.py\t{len(body)}\t{hashlib.sha256(body).hexdigest()}\n"
    (rec / "manifest.tsv").write_text(man)
    pins = tmp_path / "pins.json"
    pins.write_text(json.dumps({"manifest.tsv": hashlib.sha256(man.encode()).hexdigest()}))
    assert vi.main(["recovered", "--dir", str(rec), "--pins", str(pins)]) == 0


def _relink(tmp_path, rows):
    old, new = "/mnt/macdisk/openalex_pipeline", tmp_path / "data" / "openalex_pipeline"
    _tree(new / "derived" / "t", {"x.parquet": b"x"})
    m = tmp_path / "links.tsv"
    m.write_text("rel\ttarget\n" + "".join(f"{r}\t{t}\n" for r, t in rows))
    root = tmp_path / "legacy" / "v2_output"
    (root / "aug" / "t").mkdir(parents=True)
    (root / "aug").chmod(0o555)                                     # the boot makes /data/legacy read-only
    rc = vi.main(["relink", "--map", str(m), "--root", str(root), "--old", old, "--new", str(new)])
    return rc, root, new


def test_relink_recreates_the_links_under_the_new_data_root(tmp_path):
    rc, root, new = _relink(tmp_path, [("aug/t/x.parquet", "/mnt/macdisk/openalex_pipeline/derived/t/x.parquet")])
    assert rc == 0 and (root / "aug" / "t" / "x.parquet").is_symlink()
    assert (root / "aug" / "t" / "x.parquet").resolve() == (new / "derived" / "t" / "x.parquet").resolve()
    assert (root / "aug").stat().st_mode & 0o222 == 0                # read-only again


def test_relink_refuses_a_missing_target_and_one_outside_the_old_root(tmp_path):
    rc, _, _ = _relink(tmp_path, [("aug/t/y.parquet", "/mnt/macdisk/openalex_pipeline/derived/t/missing.parquet")])
    assert rc == 1
    rc, _, _ = _relink(tmp_path / "b", [("aug/t/z.parquet", "/etc/passwd")])
    assert rc == 1


def test_relink_creates_a_missing_folder_inside_a_read_only_one(tmp_path):
    """Review (P3b): the real derived_aug has bucket=NNN/ folders that hold only links, so the sync never makes them,
    and their parents are read-only after the boot."""
    old, new = "/mnt/macdisk/openalex_pipeline", tmp_path / "data" / "openalex_pipeline"
    _tree(new / "derived" / "t", {"x.parquet": b"x"})
    root = tmp_path / "legacy" / "v2_output"
    (root / "aug" / "edges").mkdir(parents=True)
    (root / "aug" / "edges" / "real.parquet").write_bytes(b"r")
    for d in (root / "aug" / "edges", root / "aug", root):
        d.chmod(0o555)
    m = tmp_path / "links.tsv"
    m.write_text("rel\ttarget\naug/edges/bucket=000/x.parquet\t/mnt/macdisk/openalex_pipeline/derived/t/x.parquet\n")
    rc = vi.main(["relink", "--map", str(m), "--root", str(root), "--old", old, "--new", str(new)])
    link = root / "aug" / "edges" / "bucket=000" / "x.parquet"
    assert rc == 0 and link.is_symlink() and link.resolve() == (new / "derived" / "t" / "x.parquet").resolve()
    for d in (root / "aug" / "edges" / "bucket=000", root / "aug" / "edges", root / "aug", root):
        assert d.stat().st_mode & 0o222 == 0, d
