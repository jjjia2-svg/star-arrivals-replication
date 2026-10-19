#!/usr/bin/env python3
"""R1 AWS kit, Mac side: cut a payload from a commit, render the boot script, launch ONE instance,
watch it, read its result, and book its cost. It talks only to git and to the `aws` CLI; it reads
no data and runs no pipeline code.

  r1kit.py base-bundle                       once: upload the repo at the base commit (main)
  r1kit.py launch KIND JOB COMMIT [--in NAME=PATH]... [--pull S3PREFIX=LOCALDIR]... [--dry-run]
                                  [--userdata-out PATH] [--wait]
  r1kit.py test JOB --green REF [--red REF] [--select PATHS] [--extra-line L REF EXPECT ARGS BASE]...
                    [--pull S3PREFIX=LOCALDIR]... [--dry-run] [--userdata-out PATH] [--wait]
  r1kit.py test JOB --kind test_big --green REF --markers "not live" [--baseline-from JOB]
                    --pull r1/runs/<j0>/stages/=/work/j0/ [--dry-run] [--userdata-out PATH] [--wait]
  r1kit.py watch JOB | result JOB | settle JOB [--retry] | ledger

--wait watches, prints the result, then settles the cost (retrying until the instance is terminated).
Job kinds: config/r1/jobs/<kind>.json. Shared settings: config/r1/kit.json. The bucket: the
git-ignored config/r1/local.env. Committed records carry '$SAR_S3_BUCKET', never the name, and every
dry-run echo and AWS error this kit prints has the name replaced by '$SAR_S3_BUCKET'. S3 writes go only
under s3://$SAR_S3_BUCKET/r1/.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time

KIT_DIR = pathlib.Path(__file__).resolve().parent
REPO = KIT_DIR.parents[2]
CONFIG = REPO / "config" / "r1"
TEMPLATE = KIT_DIR / "userdata.sh.tmpl"
# the R1 run records and the spend ledger (data/cal2026-10r1/aws/, not shipped)
RUNS_LOCAL = REPO / "data" / "cal2026-10r1" / "aws" / "runs"
LEDGER = REPO / "data" / "cal2026-10r1" / "aws" / "spend_ledger.jsonl"
JOBS_DIR = CONFIG / "jobs"
JOB_KEYS = ("schema", "kind", "instance_type", "price_hr", "est_min", "hard_min", "root_gb",
            "sar_host", "env", "pulls", "data_sync", "copy_from_tip", "steps")
#: optional job key: local dirs that launch flags must fill (--pull S3PREFIX=DIR), e.g. ["/work/merged/"]
OPTIONAL_JOB_KEYS = ("required_dests", "env_layers", "stages", "upstream_dests")
#: cached environment layers (V3-ENV, ruling R8): restored from r1/env/ pinned tarballs at boot
ENV_LAYERS = ("py", "rmac", "rcloud", "tex")
ENV_KEY_RE = re.compile(r"^r1/env/[a-z0-9._-]+\.tar\.gz$")
#: EC2 accepts at most 16 KB of user-data in raw form, before base64
MAX_USERDATA_BYTES = 16384
HARD_MIN_MAX = 2880  # backstop for a stuck machine (a run powers off when it ends); only J1b goes past 600
#: the full suite: the root tests AND the ported units (pytest.ini's testpaths is only tests/)
SUITE_ARGS = "-q tests pipeline/units"
#: a pulled upstream run, whose RESULT.txt must start with OK at boot
STAGES_PULL = re.compile(r"^r1/runs/([a-z0-9][a-z0-9-]{2,40})/stages/$")
UPSTREAM = re.compile(r"^r1/(runs/[a-z0-9][a-z0-9-]{2,40}/out/files|recovered/[a-z0-9][a-z0-9-]{2,40})/$")
#: bucket names seen this process; printed text shows '$SAR_S3_BUCKET' instead
REDACT: set = set()
JOB_ID = re.compile(r"^[a-z0-9][a-z0-9-]{2,40}$")
BUCKET = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
SAFE_PATH = re.compile(r'^/[^"$`\\\n]+$')
ENV_KEY = re.compile(r"^[A-Z_][A-Z0-9_]*$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
LIVE_STATES = "pending,running,stopping,stopped,shutting-down"
END_TIME = re.compile(r"\((\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) GMT\)")


class KitError(RuntimeError):
    """Anything that must stop a launch before money is spent, or a record that cannot be booked."""


# ---- configuration ------------------------------------------------------------------------------
def load_env(path=None) -> dict:
    path = pathlib.Path(path) if path else CONFIG / "local.env"
    if not path.is_file():
        raise KitError(f"{path} is missing - copy config/r1/local.env.example to it and fill it in")
    env = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"')
    if not BUCKET.match(env.get("SAR_S3_BUCKET", "")):
        raise KitError("SAR_S3_BUCKET in config/r1/local.env is empty or malformed")
    env.setdefault("AWS_REGION", "us-east-1")
    return env


def use_env(env=None) -> dict:
    """The env to use (load it if not given); registers its bucket name for redaction and the r1/ guard."""
    env = env or load_env()
    if not BUCKET.match(env.get("SAR_S3_BUCKET", "")):
        raise KitError("SAR_S3_BUCKET is empty or malformed")
    REDACT.add(env["SAR_S3_BUCKET"])
    return env


ARN = re.compile(r"arn:aws:[^\s\"']+")
ACCOUNT_ID = re.compile(r"(?<!\d)\d{12}(?!\d)")


def _redact(text) -> str:
    """The bucket name, any ARN and any 12-digit account id never reach printed output (global constraint)."""
    out = str(text)
    for b in sorted(REDACT, key=len, reverse=True):
        out = out.replace(b, "$SAR_S3_BUCKET")
    out = ARN.sub("<arn>", out)
    return ACCOUNT_ID.sub("<account>", out)


def load_kit(path=None) -> dict:
    kit = json.loads((pathlib.Path(path) if path else CONFIG / "kit.json").read_text(encoding="utf-8"))
    for k in ("region", "ami", "iam_instance_profile", "project_tag", "repo_base_commit", "ebs_usd_per_gb_month"):
        if k not in kit:
            raise KitError(f"config/r1/kit.json lacks {k}")
    if not COMMIT.match(kit["repo_base_commit"]):
        raise KitError("repo_base_commit must be a full 40-hex commit")
    return kit


def load_job(kind, jobs_dir=None) -> dict:
    p = (pathlib.Path(jobs_dir) if jobs_dir else JOBS_DIR) / f"{kind}.json"
    if not p.is_file():
        raise KitError(f"no job spec {p}")
    job = json.loads(p.read_text(encoding="utf-8"))
    missing = [k for k in JOB_KEYS if k not in job]
    unknown = [k for k in job if k not in JOB_KEYS + OPTIONAL_JOB_KEYS]
    if missing or unknown or job["schema"] != "sar.r1.job.v1" or job["kind"] != kind:
        raise KitError(f"{p.name}: bad job spec (missing {missing}, unknown {unknown})")
    req = job.setdefault("required_dests", [])
    if not isinstance(req, list) or not all(isinstance(d, str) and SAFE_PATH.match(d) for d in req):
        raise KitError(f"{p.name}: required_dests must be a list of absolute local dirs")
    up = job.setdefault("upstream_dests", [])
    if not isinstance(up, list) or not set(up) <= set(req):
        raise KitError(f"{p.name}: upstream_dests must be a sublist of required_dests")
    if not (0 < job["est_min"] < job["hard_min"] <= HARD_MIN_MAX):
        raise KitError(f"{p.name}: need 0 < est_min < hard_min <= {HARD_MIN_MAX}")
    if job["sar_host"] not in ("ec2-r1-test", "ec2-r1"):
        raise KitError(f"{p.name}: sar_host must be ec2-r1-test or ec2-r1")
    if not job["steps"]:
        raise KitError(f"{p.name}: no steps")
    check_env_layers(job.get("env_layers") or [])
    st = job.get("stages")
    if st is not None and not (isinstance(st, str) and re.match(r"^config/r1/stages/[a-z0-9_]+\.json$", st)):
        raise KitError(f"{p.name}: stages must be a path config/r1/stages/<name>.json")
    return job


def check_env_layers(layers) -> None:
    layers = list(layers or [])
    bad = [x for x in layers if x not in ENV_LAYERS]
    if bad or len(set(layers)) != len(layers):
        raise KitError(f"env_layers {layers}: each of {ENV_LAYERS}, at most once")
    if layers and "py" not in layers:
        raise KitError(f"env_layers {layers}: the py layer is required when any layer is restored")


def env_layout(text) -> dict:
    """{'rmac': R version, 'rcloud': R version, 'tex': texlive year} from config/r1/expected_versions.txt."""
    out = {}
    for line in str(text).splitlines():
        parts = line.split("\t")
        if len(parts) >= 3 and not line.startswith("#"):
            if parts[0] in ("rmac", "rcloud") and parts[1] == "R":
                out[parts[0]] = parts[2].strip()
            elif parts[0] == "tex" and parts[1] == "texlive":
                out["tex"] = parts[2].strip()
    return out


PIP_VENV = ('python3 -m venv /work/venv && /work/venv/bin/pip install -q -r "$REPO_DIR/setup/requirements.txt" '
            '|| { st "FAIL pip"; exit 1; }\n'
            '/work/venv/bin/python -c "import sys,duckdb,pandas,pyarrow,numpy;print(sys.version.split()[0],'
            'duckdb.__version__,pandas.__version__,pyarrow.__version__,numpy.__version__)" > /work/out/versions.txt')


def render_env_restore(layers, pins, layout, *, sar_host="ec2-r1") -> str:
    """Boot lines: the old pip venv for a job without layers; else each pinned layer downloaded, sha-checked and
    unpacked (R layers also install their R .deb), then versions_check.py from the commit (drift stops the boot)."""
    layers = list(layers or [])
    if not layers:
        return PIP_VENV
    check_env_layers(layers)
    out = ["mkdir -p /work/env"]
    for layer in layers:
        pin = (pins or {}).get(layer)
        if not pin:
            raise KitError(f"env layer {layer} has no pin in config/r1/env_pins.json - run the envbuild job first")
        if not ENV_KEY_RE.match(str(pin.get("key", ""))) or not SHA256.match(str(pin.get("sha256", ""))):
            raise KitError(f"env layer {layer}: bad pin {pin}")
        f = f"/work/env/{layer}.tar.gz"
        out += [f'aws s3 cp --only-show-errors "$B/{pin["key"]}" {f} || {{ st "FAIL env download {layer}"; exit 1; }}',
                f'echo "{pin["sha256"]}  {f}" | sha256sum -c --quiet - || {{ st "FAIL env sha {layer}"; exit 1; }}',
                f'tar -xzf {f} -C / || {{ st "FAIL env unpack {layer}"; exit 1; }}']
        if layer in ("rmac", "rcloud") and not any("r_runtime_apt.txt" in x for x in out):
            out.append("DEBIAN_FRONTEND=noninteractive apt-get install -y -q "
                       '$(sed -e \'s/#.*//\' "$REPO_DIR/config/r1/r_runtime_apt.txt") '
                       '|| { st "FAIL env runtime libs"; exit 1; }')
        if layer in ("rmac", "rcloud"):
            ver = layout.get(layer)
            if not ver:
                raise KitError(f"env layer {layer}: no R version in config/r1/expected_versions.txt")
            out.append(f"DEBIAN_FRONTEND=noninteractive apt-get install -y -q /opt/sar-env/{layer}/r-{ver}_1_amd64.deb "
                       f'|| {{ st "FAIL env deb {layer}"; exit 1; }}')
    out += ['git -C "$REPO_DIR" show "$COMMIT:pipeline/aws/r1/versions_check.py" > /work/versions_check.py '
            '|| { st "FAIL copy versions_check"; exit 1; }',
            f'SAR_HOST={sar_host} /work/venv/bin/python /work/versions_check.py --expected "$REPO_DIR/config/r1/expected_versions.txt" '
            f'--repo "$REPO_DIR" --layers {",".join(layers)} --out /work/out/versions.txt '
            '|| { echo VERSIONS_DRIFT > /work/out/RESULT.txt; st "FAIL versions"; exit 1; }']
    return "\n".join(out)


def base_bundle_sha() -> str:
    p = CONFIG / "repo_base.sha256"
    if not p.is_file():
        raise KitError("config/r1/repo_base.sha256 is missing - run `r1kit.py base-bundle` once")
    sha = p.read_text(encoding="utf-8").split()[0]
    if not SHA256.match(sha):
        raise KitError("config/r1/repo_base.sha256 does not hold a sha256")
    return sha


# ---- helpers ------------------------------------------------------------------------------------
def sha256_file(p) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


#: aws s3 options that take a value (the value is not a positional path)
S3_VALUED = {"--exclude", "--include", "--region", "--storage-class", "--acl", "--sse", "--content-type", "--cache-control",
             "--expires", "--metadata-directive", "--grants", "--profile", "--endpoint-url", "--source-region",
             "--page-size", "--sse-kms-key-id"}


def _check_s3_write(args) -> None:
    """The instance role can write the whole bucket (the RK originals, the u1_* tables). This kit
    writes only under s3://<bucket>/r1/."""
    if args[:1] != ["s3"] or len(args) < 2 or args[1] not in ("cp", "sync", "mv", "rm"):
        return
    pos, skip = [], False
    for a in args[2:]:
        if skip:
            skip = False
            continue
        if a.startswith("-") and a != "-":
            skip = a in S3_VALUED
            continue
        pos.append(a)
    target = pos[0] if args[1] == "rm" and pos else (pos[1] if len(pos) > 1 else "")
    if target.startswith("s3://") and not any(target.startswith(f"s3://{b}/r1/") for b in REDACT):
        raise KitError(_redact(f"refusing an S3 write to {target}: writes go only under s3://$SAR_S3_BUCKET/r1/"))


def aws(args, *, dry_run=False) -> str:
    args = [str(a) for a in args]
    _check_s3_write(args)
    if dry_run:
        print(_redact("DRY-RUN aws " + " ".join(shlex.quote(a) for a in args)))
        return ""
    r = subprocess.run(["aws", *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise KitError(_redact(f"aws {' '.join(args[:2])} failed (rc {r.returncode}): {r.stderr.strip()[:300]}"))
    return r.stdout


def git(*args, cwd=None) -> str:
    r = subprocess.run(["git", *args], cwd=cwd or REPO, capture_output=True, text=True)
    if r.returncode != 0:
        raise KitError(f"git {' '.join(args[:2])} failed: {r.stderr.strip()[:300]}")
    return r.stdout.strip()


def resolve_commit(ref) -> str:
    return git("rev-parse", "--verify", f"{ref}^{{commit}}")


def require_clean_tree(cwd=None) -> None:
    """Untracked files count on purpose (a new file nobody committed would be missing from the payload);
    git-ignored files (config/r1/local.env, .superpowers/) do not show in --porcelain."""
    if git("status", "--porcelain", cwd=cwd):
        raise KitError("the working tree is not clean (untracked files count, ignored ones do not): "
                       "commit first - payloads are cut from commits")


def make_inc_bundle(base, tip, out, *, cwd=None, branch="r1-code") -> None:
    for anc, desc in ((base, tip), (tip, f"refs/heads/{branch}")):
        r = subprocess.run(["git", "merge-base", "--is-ancestor", anc, desc], cwd=cwd or REPO, capture_output=True)
        if r.returncode != 0:
            raise KitError(f"{anc[:12]} is not an ancestor of {desc}")
    git("bundle", "create", str(out), f"{base}..refs/heads/{branch}", cwd=cwd)


def write_payload(in_dir, files) -> list:
    in_dir = pathlib.Path(in_dir)
    for name in files:
        if "/" in name or name.startswith(".") or name == "payload.sha256":
            raise KitError(f"bad payload name {name!r}")
    in_dir.mkdir(parents=True, exist_ok=False)
    rows = []
    for name, src in sorted(files.items()):
        dst = in_dir / name
        shutil.copyfile(src, dst)
        rows.append((sha256_file(dst), name))
    (in_dir / "payload.sha256").write_text("".join(f"{s}  {n}\n" for s, n in rows), encoding="utf-8")
    return rows


def hourly_usd(job, kit) -> float:
    return float(job["price_hr"]) + float(job["root_gb"]) * float(kit["ebs_usd_per_gb_month"]) / 730.0


def ledger_append(entry, path=None) -> None:
    path = pathlib.Path(path) if path else LEDGER
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")


def ledger_totals(path=None) -> dict:
    path = pathlib.Path(path) if path else LEDGER
    reserved, settled, manual = {}, {}, 0.0
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            e = json.loads(line)
            if e["event"] == "reserve":
                reserved[e["job"]] = float(e["reserved_usd"])
            elif e["event"] == "settle":
                settled[e["job"]] = float(e["actual_usd"])
            elif e["event"] == "manual":
                manual += float(e["actual_usd"])
    return {"actual_usd": round(manual + sum(settled.values()), 2),
            "open_reservations_usd": round(sum(v for j, v in reserved.items() if j not in settled), 2),
            "launches": len(reserved), "settled": len(settled)}


def iso(epoch) -> str:
    return dt.datetime.fromtimestamp(int(epoch), dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_time(s) -> float:
    return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()


# ---- rendering ----------------------------------------------------------------------------------
def _git_show(commit, path) -> str:
    return git("show", f"{commit}:{path}")


def _git_exists(commit, path) -> bool:
    return subprocess.run(["git", "cat-file", "-e", f"{commit}:{path}"], cwd=REPO, capture_output=True).returncode == 0


#: the isolation, gate and custody rows a stage table must carry before it may be marked complete (F30, V3-FINAL);
#: keyed by the table's "job". A complete table of a job not listed here is a problem too (fail closed).
REQUIRED_STAGES = {
    "j0": ("verify_inputs", "relink", "config", "sandbox", "frames_econ920", "pairs_pin", "frames", "cells_rmac",
           "cells_rcloud", "sandbox_check", "gate1"),
    "j1a": ("verify_inputs", "relink", "config", "sandbox", "gate1_link", "rank_gate", "rank_tables", "events",
            "frames", "cells_rmac", "cells_rcloud", "estimates_m", "promote", "sandbox_check"),
    "j1b": ("verify_inputs", "config", "restore_j1a", "sandbox", "sandbox_check"),
    "final": ("verify_inputs", "config", "canon", "custody", "sentinel_pre", "sentinel_post", "gate2"),
    "finalb0": ("verify_inputs", "config", "sentinel_pre", "sentinel_post", "gate2"),
    "jp": ("repo_manifest", "cells_rmac", "cells_rcloud", "compare"),
}


def check_stage_table(job, commit, *, show=None, exists=None) -> list:
    """Problems that must stop a real launch of a multi-stage job (ruling R9); [] when ready. A table marked
    complete must also carry its REQUIRED_STAGES (F30), so 'complete' cannot run ahead of the isolation rows."""
    show = show or (lambda p: _git_show(commit, p))
    exists = exists or (lambda p: _git_exists(commit, p))
    path = job.get("stages")
    if not path:
        return []
    try:
        t = json.loads(show(path))
    except (KitError, ValueError) as e:
        return [f"{path}: not readable at {commit[:12]} ({e})"]
    probs = [] if t.get("complete") else [f"{path}: incomplete (complete=false; F30 sets it after the review)"]
    if t.get("complete"):
        need = REQUIRED_STAGES.get(t.get("job"))
        lack = [n for n in need or () if n not in {s.get("name") for s in t.get("stages", [])}]
        if need is None:
            probs.append(f"{path}: complete, but job {t.get('job')!r} has no REQUIRED_STAGES entry")
        elif lack:
            probs.append(f"{path}: complete, but lacks required stages {lack}")
    for s in t.get("stages", []):
        for p in ([s["script"]] if s.get("script") else []) + list(s.get("requires", [])):
            if not exists(p):
                probs.append(f"stage {s.get('name')}: {p} is not in commit {commit[:12]}")
    return probs


def render(template, values) -> str:
    out = template
    for k, v in values.items():
        out = out.replace(f"@@{k}@@", v)
    left = sorted(set(re.findall(r"@@[A-Z_]+@@", out)))
    if left:
        raise KitError(f"unfilled template fields {left}")
    return out


def _sync_lines(pairs) -> str:
    """Boot lines for the pulls. `aws s3 sync` of a prefix that does not exist exits 0, so every pull must
    also bring at least one file; a pulled upstream run (r1/runs/<job>/out/files/, r1/recovered/<job>/)
    must have passed: its RESULT.txt starts with OK."""
    lines = []
    for src, dest in pairs:
        src, dest = str(src), str(dest)
        if src.startswith("/") or ".." in src or not src.endswith("/") or not SAFE_PATH.match(dest):
            raise KitError(f"bad pull {src!r} -> {dest!r} (an S3 prefix ending in '/', an absolute local dir)")
        d = dest.rstrip("/")
        line = (f'mkdir -p "{d}" && aws s3 sync --only-show-errors "$B/{src}" "{d}/" '
                f'|| {{ st "FAIL pull {src}"; exit 1; }}\n'
                f'[ -n "$(ls -A "{d}")" ] || {{ st "FAIL empty pull {src}"; exit 1; }}')
        if UPSTREAM.match(src):
            line += (f"\n[ \"$(awk 'NR==1{{print $1}}' \"{d}/RESULT.txt\" 2>/dev/null)\" = OK ] "
                     f"|| {{ st \"FAIL upstream not OK {src}\"; exit 1; }}")
        sp = STAGES_PULL.match(src)
        if sp and d != "/work/resume":          # a stage set used as an input (not a resume) must come from a passed job
            line += (f"\n[ \"$(aws s3 cp --only-show-errors \"$B/r1/runs/{sp.group(1)}/out/files/RESULT.txt\" - 2>/dev/null "
                     f"| awk 'NR==1{{print $1}}')\" = OK ] || {{ st \"FAIL upstream not OK {src}\"; exit 1; }}")
        lines.append(line)
    return "\n".join(lines) if lines else ":"


def render_steps_script(job, *, job_id, commit, repo_dir, bucket, layout=None, extra_env=None) -> str:
    lines = ["#!/bin/bash",
             "export PATH=/snap/bin:/usr/local/bin:/usr/bin:/bin HOME=/home/ubuntu",
             f'export B="s3://{bucket}" JOB="{job_id}" COMMIT="{commit}" REPO_DIR="{repo_dir}" PY=/work/venv/bin/python',
             'export P="$B/r1/runs/$JOB"',
             f'export SAR_HOST="{job["sar_host"]}"']
    for k, v in sorted(job["env"].items()) + sorted((extra_env or {}).items()):
        if not ENV_KEY.match(k):
            raise KitError(f"bad env name {k!r}")
        lines.append(f"export {k}={shlex.quote(str(v).replace('$REPO_DIR', repo_dir))}")
    layers = list(job.get("env_layers") or [])
    if layers and layout:
        lines.append("export R_PROFILE_USER=/dev/null RGL_USE_NULL=TRUE")
        rl = [x for x in ("rmac", "rcloud") if x in layers and layout.get(x)]
        for x in rl:
            lines.append(f"export SAR_RSCRIPT_{x.upper()}=/opt/R/{layout[x]}/bin/Rscript SAR_RLIB_{x.upper()}=/opt/sar-env/rlib-{x}")
        if rl:
            lines.append(f"export R_LIBS=/opt/sar-env/rlib-{rl[0]}")
        path = ([f"/opt/texlive/{layout['tex']}/bin/x86_64-linux"] if "tex" in layers and layout.get("tex") else []) + \
               ([f"/opt/R/{layout[rl[0]]}/bin"] if rl else [])
        if path:
            lines.append(f"export PATH={':'.join(path)}:$PATH")
    lines += ['st() { echo "$(date -u +%FT%TZ) $*" > "/tmp/st.$$"; aws s3 cp --only-show-errors "/tmp/st.$$" "$P/status.txt"; }',
              "cd /work || exit 1"]
    for i, step in enumerate(job["steps"], 1):
        lines.append(f'( {step} ); rc=$?; [ "$rc" -eq 0 ] || {{ st "FAIL step {i} rc=$rc"; exit "$rc"; }}')
    lines.append("exit 0")
    return "\n".join(lines) + "\n"


def render_userdata(job, *, job_id, commit, repo_dir, bucket, base_sha, deadline_epoch, extra_pulls=(),
                    env_pins=None, expected_text=None, extra_env=None) -> str:
    if not JOB_ID.match(job_id):
        raise KitError(f"bad job id {job_id!r}")
    if not COMMIT.match(commit):
        raise KitError(f"bad commit {commit!r}")
    if not SAFE_PATH.match(repo_dir):
        raise KitError(f"unsafe repo dir {repo_dir!r}")
    if not BUCKET.match(bucket):
        raise KitError("bad bucket name")
    if not SHA256.match(base_sha):
        raise KitError("bad base bundle sha")
    copies = []
    for src, dst in job["copy_from_tip"]:
        if src.startswith("/") or ".." in src or not SAFE_PATH.match(dst):
            raise KitError(f"bad copy_from_tip {src!r} -> {dst!r}")
        copies.append(f'git -C "$REPO_DIR" show "$COMMIT:{src}" > "{dst}" || {{ st "FAIL copy {src}"; exit 1; }}')
    layers = list(job.get("env_layers") or [])
    layout = {}
    if layers:
        if expected_text is None:
            expected_text = (CONFIG / "expected_versions.txt").read_text(encoding="utf-8")
        if env_pins is None:
            pf = CONFIG / "env_pins.json"
            env_pins = json.loads(pf.read_text(encoding="utf-8")).get("layers", {}) if pf.is_file() else {}
        layout = env_layout(expected_text)
    env_restore = render_env_restore(layers, env_pins, layout, sar_host=job["sar_host"])
    steps = render_steps_script(job, job_id=job_id, commit=commit, repo_dir=repo_dir, bucket=bucket,
                                layout=layout or None, extra_env=extra_env)
    text = render(TEMPLATE.read_text(encoding="utf-8"), {
        "HARD_MIN": str(int(job["hard_min"])),
        "DEADLINE_EPOCH": str(int(deadline_epoch)),
        "BUCKET": bucket, "JOB": job_id, "COMMIT": commit, "REPO_DIR": repo_dir,
        "BASE_BUNDLE_SHA": base_sha,
        "COPY_FROM_TIP": "\n".join(copies) if copies else ":",
        "PULLS": _sync_lines(list(job["pulls"]) + [tuple(p) for p in extra_pulls]),
        "DATA_SYNC": _sync_lines(job["data_sync"]),
        "STEPS_SCRIPT": steps.rstrip("\n"),
        "ENV_RESTORE": env_restore,
    })
    n = len(text.encode("utf-8"))
    if n >= MAX_USERDATA_BYTES:
        raise KitError(f"rendered user-data is {n} bytes; EC2 accepts at most 16 KB ({MAX_USERDATA_BYTES} bytes) raw")
    return text


# ---- AWS actions --------------------------------------------------------------------------------
def live_instances(region, project) -> list:
    out = aws(["ec2", "describe-instances", "--region", region,
               "--filters", f"Name=tag:Project,Values={project}", f"Name=instance-state-name,Values={LIVE_STATES}",
               "--query", "Reservations[].Instances[].InstanceId", "--output", "text"])
    return out.split()


def launch(kind, job_id, commit_ref, *, in_files=None, extra_pulls=(), dry_run=False,
           env=None, kit=None, now=None, repo_dir=None, userdata_out=None, resume_from=None) -> dict:
    if not JOB_ID.match(job_id):
        raise KitError(f"bad job id {job_id!r}")
    env = use_env(env)
    kit = kit or load_kit()
    job = load_job(kind)
    extra_env = {}
    if resume_from:
        if not JOB_ID.match(resume_from):
            raise KitError(f"bad --resume-from job id {resume_from!r}")
        extra_pulls = [*extra_pulls, (f"r1/runs/{resume_from}/stages/", "/work/resume/")]
        extra_env["SAR_RESUME_DIR"] = "/work/resume"
    have = {str(d).rstrip("/") for _, d in list(job["pulls"]) + [tuple(p) for p in extra_pulls]}
    need = [d for d in job["required_dests"] if d.rstrip("/") not in have]
    up = {d.rstrip("/") for d in job.get("upstream_dests") or []}
    wrong = [s for s, d in list(job["pulls"]) + [tuple(p) for p in extra_pulls]
             if str(d).rstrip("/") in up and not UPSTREAM.match(str(s))]
    if wrong:
        raise KitError(f"job kind {kind} reads an upstream run's results into {sorted(up)}: pull "
                       f"r1/runs/<job>/out/files/ there, not {wrong}")
    if need:
        raise KitError(f"job kind {kind} needs pulls into {need}: pass --pull S3PREFIX=DIR for each "
                       f"(the upstream job ids come from the progress ledger)")
    if userdata_out:
        uo = pathlib.Path(userdata_out).resolve()
        if uo == REPO.resolve() or REPO.resolve() in uo.parents:
            raise KitError("--userdata-out must be outside the repo (it names the bucket)")
    run_dir = RUNS_LOCAL / job_id
    if (run_dir / "launch_record.json").exists():
        raise KitError(f"{job_id} was launched already - use a new job id")
    if not dry_run:
        require_clean_tree()
    commit = resolve_commit(commit_ref)
    env_pins = expected_text = None
    if job.get("env_layers"):                  # the commit's pins: the same file the stage fingerprints read
        try:
            env_pins = json.loads(_git_show(commit, "config/r1/env_pins.json")).get("layers", {})
        except (KitError, ValueError):
            env_pins = {}
        expected_text = _git_show(commit, "config/r1/expected_versions.txt")
    probs = check_stage_table(job, commit)
    if probs and dry_run:
        for pr in probs:
            print(f"INCOMPLETE STAGE TABLE: {pr}")
    elif probs:
        raise KitError("stage table incomplete or not ready: " + "; ".join(probs))
    region, bucket = kit["region"], env["SAR_S3_BUCKET"]
    now = int(now if now is not None else time.time())
    deadline = now + 60 * (int(job["hard_min"]) + 10)
    reserve = round(hourly_usd(job, kit) * (int(job["hard_min"]) + 10) / 60.0, 2)
    with tempfile.TemporaryDirectory(prefix="sar-r1-") as td:
        td = pathlib.Path(td)
        make_inc_bundle(kit["repo_base_commit"], commit, td / "inc.bundle")
        rows = write_payload(td / "in", {"inc.bundle": td / "inc.bundle", **(in_files or {})})
        ud = td / "userdata.sh"
        ud.write_text(render_userdata(job, job_id=job_id, commit=commit, repo_dir=repo_dir or str(REPO),
                                      bucket=bucket, base_sha=base_bundle_sha(), deadline_epoch=deadline,
                                      extra_pulls=extra_pulls, extra_env=extra_env or None,
                                      env_pins=env_pins, expected_text=expected_text), encoding="utf-8")
        if userdata_out:                       # for the pre-launch rehearsal; it names the bucket: never print it
            fd = os.open(str(userdata_out), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as fh:
                fh.write(ud.read_bytes())
            os.chmod(str(userdata_out), 0o600)
        if not dry_run:
            live = live_instances(region, kit["project_tag"])
            if len(live) >= int(kit.get("max_live_instances", 1)):
                raise KitError(f"refusing: a {kit['project_tag']} instance is live: {live}")
        prefix = f"s3://{bucket}/r1/runs/{job_id}"
        aws(["s3", "cp", "--only-show-errors", "--recursive", f"{td / 'in'}/", f"{prefix}/in/"], dry_run=dry_run)
        tags = (f"{{Key=Name,Value=sar-r1-{job_id}}},{{Key=Project,Value={kit['project_tag']}}},"
                f"{{Key=DeadlineUtc,Value={iso(deadline)}}}")
        bdm = json.dumps([{"DeviceName": "/dev/sda1", "Ebs": {"VolumeSize": int(job["root_gb"]), "VolumeType": "gp3",
                                                               "DeleteOnTermination": True, "Encrypted": True}}])
        iid = aws(["ec2", "run-instances", "--region", region, "--image-id", kit["ami"],
                   "--instance-type", job["instance_type"],
                   "--iam-instance-profile", f"Name={kit['iam_instance_profile']}",
                   "--instance-initiated-shutdown-behavior", "terminate",
                   "--block-device-mappings", bdm,
                   "--metadata-options", "HttpTokens=required,HttpEndpoint=enabled",
                   "--user-data", f"file://{ud}",
                   "--tag-specifications", f"ResourceType=instance,Tags=[{tags}]", f"ResourceType=volume,Tags=[{tags}]",
                   "--query", "Instances[0].InstanceId", "--output", "text"], dry_run=dry_run).strip()
        record = {"schema": "sar.r1.launch.v1", "job": job_id, "kind": kind, "commit": commit,
                  "instance_id": iid or "i-dry-run", "instance_type": job["instance_type"], "region": region,
                  "launch_utc": iso(now), "deadline_utc": iso(deadline), "est_min": job["est_min"],
                  "hard_min": job["hard_min"], "reserved_usd": reserve,
                  "payload": [{"name": n, "sha256": s} for s, n in rows],
                  "base_bundle_sha256": base_bundle_sha(), "userdata_sha256": sha256_file(ud),
                  "s3_prefix": f"s3://$SAR_S3_BUCKET/r1/runs/{job_id}",
                  "extra_pulls": [list(p) for p in extra_pulls], "resume_from": resume_from}
    if not dry_run:
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "launch_record.json").write_text(json.dumps(record, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        ledger_append({"event": "reserve", "job": job_id, "kind": kind, "instance_id": record["instance_id"],
                       "instance_type": job["instance_type"], "reserved_usd": reserve, "utc": record["launch_utc"]})
    print(f"launched {record['instance_id']} job {job_id} ({job['instance_type']}); hard deadline "
          f"{record['deadline_utc']}; reserved ${reserve}")
    return record


def read_status(env, job_id) -> str:
    try:
        return aws(["s3", "cp", "--only-show-errors", f"s3://{env['SAR_S3_BUCKET']}/r1/runs/{job_id}/status.txt", "-"]).strip()
    except KitError:
        return ""


def instance_state(region, iid) -> str:
    try:
        return aws(["ec2", "describe-instances", "--region", region, "--instance-ids", iid,
                    "--query", "Reservations[0].Instances[0].State.Name", "--output", "text"]).strip()
    except KitError as e:
        if "InvalidInstanceID" in str(e):
            return "gone"                             # AWS no longer lists it (about an hour after termination)
        raise


def _record(job_id) -> dict:
    p = RUNS_LOCAL / job_id / "launch_record.json"
    if not p.is_file():
        raise KitError(f"no launch record for {job_id}")
    return json.loads(p.read_text(encoding="utf-8"))


def watch(job_id, *, env=None, poll_s=60, now_fn=time.time, sleep_fn=time.sleep, max_polls=None) -> str:
    env = use_env(env)
    rec = _record(job_id)
    deadline = parse_time(rec["deadline_utc"])
    last, n = "", 0
    while True:
        s = read_status(env, job_id)
        if s and s != last:
            print(_redact(s), flush=True)
            last = s
        if s.split()[1:2] == ["DONE"]:
            return s
        if now_fn() > deadline + 600:
            if instance_state(rec["region"], rec["instance_id"]) != "terminated":
                aws(["ec2", "terminate-instances", "--region", rec["region"], "--instance-ids", rec["instance_id"]])
                print(f"terminated {rec['instance_id']}: past its hard deadline", flush=True)
            return s or "NO_STATUS past the hard deadline"
        n += 1
        if n % 5 == 0 and s == last and instance_state(rec["region"], rec["instance_id"]) in ("terminated", "gone"):
            return f"GONE {s or 'NO_STATUS'}"
        if max_polls is not None and n >= max_polls:
            return s
        sleep_fn(poll_s)


def result(job_id, *, env=None) -> int:
    env = use_env(env)
    base = f"s3://{env['SAR_S3_BUCKET']}/r1/runs/{job_id}/out/files"
    try:
        res = aws(["s3", "cp", "--only-show-errors", f"{base}/RESULT.txt", "-"]).strip()
    except KitError:
        res = "NO_RESULT"
    print(_redact(f"RESULT {res}"))
    for name in ("results.json", "summary.json"):
        try:
            data = json.loads(aws(["s3", "cp", "--only-show-errors", f"{base}/{name}", "-"]))
        except KitError:
            continue
        if name == "results.json":
            for r in data:
                print(_redact(f"  {r['label']:<8} {r['expect']:<9} rc={r['rc']} ok={r['ok']}  {r['why']}"))
        else:
            print(_redact(json.dumps(data, indent=1, sort_keys=True)))
    return 0 if res.split()[:1] == ["OK"] else 1


FETCH_ALWAYS = ("RESULT.txt", "results.json", "summary.json")
FETCH_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*(/[A-Za-z0-9][A-Za-z0-9_.-]*)*$")


def _stage_job(job_id) -> bool:
    """True unless this Mac's launch record names a job kind without a stage table (unknown counts as stage)."""
    try:
        kind = _record(job_id)["kind"]
        return bool(load_job(kind).get("stages"))
    except (KitError, KeyError):
        return True


def _tarball_shas(env, job_id, names) -> dict:
    """{name: sha256} of out/<name> inside the job's out/out.tar.gz, after the tarball itself matched the sha256
    in out/out.sha256 (both written by the boot script's fin). The tarball lives only in a temporary directory
    that is removed at once; only the named members are hashed, nothing is extracted."""
    import tarfile                                                          # noqa: PLC0415
    out = f"s3://{env['SAR_S3_BUCKET']}/r1/runs/{job_id}/out"
    rec = aws(["s3", "cp", "--only-show-errors", f"{out}/out.sha256", "-"]).split()
    if not rec or not SHA256.match(rec[0]):
        raise KitError(f"{job_id}: out/out.sha256 is missing or malformed")
    want = {}
    with tempfile.TemporaryDirectory(prefix="sar-r1-fetch-") as td:
        tar = pathlib.Path(td) / "out.tar.gz"
        aws(["s3", "cp", "--only-show-errors", f"{out}/out.tar.gz", str(tar)])
        if sha256_file(tar) != rec[0]:
            raise KitError(f"{job_id}: out.tar.gz differs from out/out.sha256")
        with tarfile.open(tar, "r:gz") as tf:
            for n in names:
                try:
                    m = tf.getmember(f"out/{n}")
                except KeyError:
                    raise KitError(f"{n} is not in the job's out.tar.gz") from None
                if not m.isfile():
                    raise KitError(f"{n} is not a file in the job's out.tar.gz")
                h, fh = hashlib.sha256(), tf.extractfile(m)
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
                want[n] = h.hexdigest()
    return want


def fetch(job_id, to_dir, *, names=FETCH_ALWAYS, author_ok=None, env=None) -> list:
    """S3 -> Mac. The four allowlisted names freely; anything else only with an author OK quoted in the
    record, listed in the job's files/MANIFEST.sha256 and sha-checked (global constraint 'S3 -> Mac').
    A job whose kind has no stage table writes no MANIFEST (only run_stages does): its names are checked
    against out/out.tar.gz, verified by out/out.sha256 (W2-INT, the rostermatch-02 404). Stage jobs, and
    jobs this Mac has no launch record for, keep the strict MANIFEST check."""
    env = use_env(env)
    if not JOB_ID.match(job_id):
        raise KitError(f"bad job id {job_id!r}")
    base = f"s3://{env['SAR_S3_BUCKET']}/r1/runs/{job_id}/out/files"
    extra = [n for n in names if n not in FETCH_ALWAYS]
    if any(not FETCH_NAME.match(n) for n in names):
        raise KitError(f"bad file name in {list(names)}")
    if extra and not (author_ok or "").strip():
        raise KitError(f"{extra}: S3 -> Mac carries only {FETCH_ALWAYS} unless the author OKs the fetch (--author-ok)")
    want, verified_by = {}, None
    if extra:
        try:
            manifest = aws(["s3", "cp", "--only-show-errors", f"{base}/MANIFEST.sha256", "-"])
        except KitError as e:
            if _stage_job(job_id):
                raise KitError(f"{job_id}: no files/MANIFEST.sha256 for a stage job ({e})") from None
            want, verified_by = _tarball_shas(env, job_id, extra), "out.tar.gz"
        else:
            verified_by = "MANIFEST.sha256"
            for line in manifest.splitlines():
                if line.strip():
                    sha, name = line.split(None, 1)
                    want[name.strip()] = sha
            missing = [n for n in extra if n not in want]
            if missing:
                raise KitError(f"{missing} are not in the job's MANIFEST.sha256")
    to = pathlib.Path(to_dir)
    got = []
    for n in names:
        dst = to / n
        dst.parent.mkdir(parents=True, exist_ok=True)
        aws(["s3", "cp", "--only-show-errors", f"{base}/{n}", str(dst)])
        if n in want and sha256_file(dst) != want[n]:
            dst.unlink()
            raise KitError(f"{n}: sha differs from the job's {verified_by}")
        got.append(dst)
    rec = RUNS_LOCAL / job_id / "fetch_record.json"
    old = json.loads(rec.read_text(encoding="utf-8")) if rec.is_file() else []
    old.append({"utc": iso(time.time()), "names": list(names), "sha256": {p.name: sha256_file(p) for p in got},
                "author_ok": author_ok, "verified_by": verified_by})
    rec.parent.mkdir(parents=True, exist_ok=True)
    rec.write_text(json.dumps(old, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return got


def apply_patch(patch, target) -> None:
    """The Mac side of C6: apply a patch an instance returned, dry run first; --forward refuses one already in."""
    for extra in (["--dry-run"], []):
        r = subprocess.run(["patch", "-p1", "--forward", *extra, "-d", str(target), "-i", str(patch)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise KitError(f"{patch} does not apply to {target}: {(r.stdout + r.stderr)[-300:]}")


def settle(job_id, *, env=None, kit=None) -> dict:
    env = use_env(env)
    kit = kit or load_kit()
    rec = _record(job_id)
    job = load_job(rec["kind"])
    try:
        out = aws(["ec2", "describe-instances", "--region", rec["region"], "--instance-ids", rec["instance_id"],
                   "--query", "Reservations[0].Instances[0].[LaunchTime,State.Name,StateTransitionReason]", "--output", "json"])
    except KitError as e:
        if "InvalidInstanceID" not in str(e):
            raise
        out = None                                    # AWS lists a terminated instance for about an hour only
    if out is None:
        s = read_status(env, job_id)
        launch_t, state, reason = rec["launch_utc"], "terminated (no longer listed by AWS)", ""
        if s.split()[1:2] == ["DONE"]:
            end, end_source = parse_time(s.split()[0]) + 180, "status (instance gone)"
        else:
            end, end_source = parse_time(rec["deadline_utc"]), "hard deadline (instance gone, no DONE status): upper bound"
    else:
        launch_t, state, reason = json.loads(out)
        if state != "terminated":
            raise KitError(f"{rec['instance_id']} is {state}; settle again once it is terminated")
        m = END_TIME.search(reason or "")
        if m:
            end = dt.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.timezone.utc).timestamp()
            end_source = "StateTransitionReason"
        else:
            s = read_status(env, job_id)
            if s.split()[1:2] == ["DONE"]:
                end, end_source = parse_time(s.split()[0]) + 180, "status DONE + 3 min"
            else:                                     # the fuse fired before DONE: book the fuse time, an upper bound
                end = min(parse_time(rec["deadline_utc"]), parse_time(launch_t) + 60 * (int(rec["hard_min"]) + 5))
                end_source = "fuse (no DONE status): upper bound"
    hours = round((end - parse_time(launch_t)) / 3600.0, 4)
    entry = {"event": "settle", "job": job_id, "instance_id": rec["instance_id"], "launch_utc": iso(parse_time(launch_t)),
             "end_utc": iso(end), "end_source": end_source, "hours": hours,
             "actual_usd": round(hours * hourly_usd(job, kit), 4)}
    ledger_append(entry)
    (RUNS_LOCAL / job_id / "termination_proof.json").write_text(
        json.dumps({"instance_id": rec["instance_id"], "state": state, "reason": reason}, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(entry, sort_keys=True))
    return entry


def settle_until_terminated(job_id, *, env=None, kit=None, tries=20, wait_s=30, sleep_fn=time.sleep) -> dict:
    """settle(), retried while the instance is still shutting down (no foreground `sleep` needed)."""
    for i in range(tries):
        try:
            return settle(job_id, env=env, kit=kit)
        except KitError as e:
            if "settle again" not in str(e):
                raise
            if i + 1 < tries:
                sleep_fn(wait_s)
    raise KitError(f"SETTLE PENDING: {job_id} is not terminated yet; run `r1kit.py settle {job_id} --retry` later")


def base_bundle(*, env=None, kit=None, dry_run=False) -> str:
    env = use_env(env)
    kit = kit or load_kit()
    if resolve_commit("refs/heads/main") != kit["repo_base_commit"]:
        raise KitError("main is not at repo_base_commit; the base bundle is cut from main at the base commit")
    with tempfile.TemporaryDirectory(prefix="sar-r1-base-") as td:
        b = pathlib.Path(td) / "base.bundle"
        git("bundle", "create", str(b), "refs/heads/main")
        sha = sha256_file(b)
        aws(["s3", "cp", "--only-show-errors", str(b), f"s3://{env['SAR_S3_BUCKET']}/r1/repo/base.bundle"], dry_run=dry_run)
    if not dry_run:
        (CONFIG / "repo_base.sha256").write_text(f"{sha}  base.bundle\n", encoding="utf-8")
    print(f"base bundle sha256 {sha}")
    return sha


def spec_lines_for_test(*, base, green, red=None, select="", extra=(), suite=True) -> list:
    sel = f" {select}" if select else ""
    lines = [f"base\t{base}\trecord\t{SUITE_ARGS}\t-"] if suite else []
    if red:
        lines.append(f"red\t{red}\tfail\t-q{sel}\t-")
    lines.append(f"green\t{green}\tpass\t-q{sel}\t-")
    if suite:
        lines.append(f"suite\t{green}\tnoregress\t{SUITE_ARGS}\t@base")
    for label, ref, expect, args, baseline in extra:
        lines.append("\t".join((label, ref, expect, args, baseline)))
    return lines


def spec_lines_for_big(*, green, markers, baseline=None) -> list:
    """The big-host run (gate 1b, ruling R1): the whole suite on ec2-r1 with the uploaded inputs, never `live`."""
    if not (re.fullmatch(r"not live( and .+)?", markers or "") and "live" not in markers[8:]):
        raise KitError("big mode never selects live tests (the OpenAlex key stays on the Mac): "
                       "markers must be 'not live' or 'not live and ...'")
    args = f'-q -m "{markers}" tests pipeline/units'
    return [f"big\t{green}\t{'noregress' if baseline else 'record'}\t{args}\t{baseline or '-'}"]


def baseline_pulls(job_id) -> list:
    """--baseline-from: the pull of a prior big-host run's out/files. It must name a test_big job (the kind in its
    launch record), so a small-runner record can never become the big suite's noregress baseline."""
    if not JOB_ID.match(str(job_id)):
        raise KitError(f"bad --baseline-from job id {job_id!r}")
    kind = _record(job_id).get("kind")
    if kind != "test_big":
        raise KitError(f"--baseline-from {job_id} is a {kind!r} job; it must name a test_big job")
    return [(f"r1/runs/{job_id}/out/files/", "/work/bigbase/")]


def _pairs(items, what) -> list:
    out = []
    for it in items:
        if "=" not in it:
            raise KitError(f"{what} wants NAME=VALUE, got {it!r}")
        out.append(tuple(it.split("=", 1)))
    return out


def _finish_wait(job) -> int:
    """--wait: watch, print the result, then book the cost (retrying until the instance is terminated)."""
    watch(job)
    rc = result(job)
    try:
        settle_until_terminated(job)
    except KitError as e:
        print(f"SETTLE PENDING: {e}", flush=True)
    print(json.dumps(ledger_totals(), sort_keys=True), flush=True)
    return rc


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="R1 AWS kit (Mac side)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("base-bundle").add_argument("--dry-run", action="store_true")
    la = sub.add_parser("launch")
    la.add_argument("kind")
    la.add_argument("job")
    la.add_argument("commit")
    la.add_argument("--in", dest="ins", action="append", default=[], metavar="NAME=PATH")
    la.add_argument("--pull", action="append", default=[], metavar="S3PREFIX=LOCALDIR")
    la.add_argument("--dry-run", action="store_true")
    la.add_argument("--userdata-out", type=pathlib.Path)
    la.add_argument("--wait", action="store_true")
    la.add_argument("--resume-from", metavar="JOB")
    te = sub.add_parser("test")
    te.add_argument("job")
    te.add_argument("--green", required=True)
    te.add_argument("--red")
    te.add_argument("--select", default="")
    te.add_argument("--no-suite", action="store_true")
    te.add_argument("--extra-line", nargs=5, action="append", default=[],
                    metavar=("LABEL", "REF", "EXPECT", "ARGS", "BASELINE"))
    te.add_argument("--dry-run", action="store_true")
    te.add_argument("--userdata-out", type=pathlib.Path)
    te.add_argument("--wait", action="store_true")
    te.add_argument("--kind", default="test", choices=("test", "test_big"))
    te.add_argument("--markers")
    te.add_argument("--baseline-from", metavar="JOB")
    # a job kind's required_dests (test_big: J0's stage set at /work/j0/, B4 t-big-04) are filled like launch's
    te.add_argument("--pull", action="append", default=[], metavar="S3PREFIX=LOCALDIR")
    for name in ("watch", "result"):
        sub.add_parser(name).add_argument("job")
    se = sub.add_parser("settle")
    se.add_argument("job")
    se.add_argument("--retry", action="store_true", help="retry every 30 s (up to 10 min) until terminated")
    sub.add_parser("ledger")
    ap_ = sub.add_parser("apply-patch")
    ap_.add_argument("patch", type=pathlib.Path)
    ap_.add_argument("--target", required=True, type=pathlib.Path)
    fe = sub.add_parser("fetch")
    fe.add_argument("job")
    fe.add_argument("--to", required=True, type=pathlib.Path)
    fe.add_argument("--name", action="append", default=[])
    fe.add_argument("--author-ok")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "base-bundle":
            base_bundle(dry_run=a.dry_run)
            return 0
        if a.cmd == "launch":
            ins = {n: pathlib.Path(p) for n, p in _pairs(a.ins, "--in")}
            launch(a.kind, a.job, a.commit, in_files=ins, extra_pulls=_pairs(a.pull, "--pull"), dry_run=a.dry_run,
                   userdata_out=a.userdata_out, resume_from=a.resume_from)
            if a.wait and not a.dry_run:
                return _finish_wait(a.job)
            return 0
        if a.cmd == "test":
            extra_pulls = _pairs(a.pull, "--pull")
            kit = load_kit()
            pulls = []
            if a.kind == "test_big":
                if not a.markers or a.red or a.select or a.extra_line:
                    raise KitError("--kind test_big needs --markers and takes no --red/--select/--extra-line")
                if a.baseline_from:
                    pulls = baseline_pulls(a.baseline_from)
                lines = spec_lines_for_big(green=resolve_commit(a.green), markers=a.markers,
                                           baseline="/work/bigbase/big.xml" if a.baseline_from else None)
            else:
                extra = [(lab, resolve_commit(ref), exp, args, bl) for lab, ref, exp, args, bl in a.extra_line]
                lines = spec_lines_for_test(base=kit["repo_base_commit"], green=resolve_commit(a.green),
                                            red=resolve_commit(a.red) if a.red else None, select=a.select,
                                            extra=extra, suite=not a.no_suite)
            pulls = [*pulls, *extra_pulls]
            with tempfile.TemporaryDirectory(prefix="sar-r1-t-") as td:
                spec = pathlib.Path(td) / "tests.tsv"
                spec.write_text("\n".join(lines) + "\n", encoding="utf-8")
                print(spec.read_text(encoding="utf-8"), end="")
                launch(a.kind, a.job, a.green, in_files={"tests.tsv": spec}, dry_run=a.dry_run, kit=kit,
                       userdata_out=a.userdata_out, extra_pulls=pulls)
            if a.wait and not a.dry_run:
                return _finish_wait(a.job)
            return 0
        if a.cmd == "watch":
            print(_redact(watch(a.job)))        # the returned status line can carry the bucket (FIX-JP 6)
            return 0
        if a.cmd == "result":
            return result(a.job)
        if a.cmd == "settle":
            settle_until_terminated(a.job) if a.retry else settle(a.job)
            return 0
        if a.cmd == "apply-patch":
            apply_patch(a.patch, a.target)
            print(f"applied {a.patch.name}")
            return 0
        if a.cmd == "fetch":
            got = fetch(a.job, a.to, names=tuple(a.name) or FETCH_ALWAYS, author_ok=a.author_ok)
            print(f"fetched {len(got)} file(s)")
            return 0
        if a.cmd == "ledger":
            print(json.dumps(ledger_totals(), indent=1, sort_keys=True))
            return 0
    except KitError as e:
        print(_redact(f"KIT ERROR: {e}"), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
