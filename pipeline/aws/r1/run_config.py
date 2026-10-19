#!/usr/bin/env python3
"""R1 run-config chain step (F23). Runs on an R1 instance, inside the F2 sandbox. Standard library only.

  run_config.py --config CFG.json --chain config/r1/chain.json --step NAME --repo DIR --work DIR --out STAGE_OUT
  run_config.py --plan --config CFG.json --chain config/r1/chain.json --repo DIR --work DIR [--step NAME]

One stage row of a job table runs one step of the chain (config/r1/chain.json, schema sar.r1.chain.v1): every
invocation of the step in order, cwd = the repo, and the first non-zero exit ends the step. The environment
is the caller's plus the step's `env` and
  SAR_R1_CONFIG   the config file (October callers read their stage section through pipeline/lib/r1_config.py)
  SAR_OUT_ROOT    a fresh empty dir under $WORK/tmp/<step>/ (the builders' scratch root)
  PATH            dirname($SAR_RSCRIPT_RMAC) first: October's in-chain R controls ran on the Mac stack
  R_LIBS          $SAR_RLIB_RMAC, when set
  PYTHONHASHSEED  0
Placeholders in argv and env values: {py} (the job's python), {repo}, {work}, {out} (STAGE_OUT), {tmp}
($WORK/tmp/<step>, emptied first) and {cfg:SECTION.KEY} (the config's resolved value). Writes
STAGE_OUT/step_report.json {rc, secs, config sha256, sha256 of each declared write}; post 'copy_frames'
copies the step's frames_dir (with its MANIFEST.sha256) to $WORK/prod/frames (ruling R10).

The config is read against the repository it is committed in (<repo>/config/r1/<name>.json): on an instance
that is $REPO_DIR. A step reads only the config's name and sha256; the full loader (pipeline/lib/r1_config.py,
every STOP rule) runs only when an argv item names {cfg:...}, and always under --plan. The full check is the
job's `config` row, before the sandbox: B0.json's `inputs` name October products (the event tables, the aug
restake table) that the sandbox moves away until restake/write_events rebuild them, so a full load in the
first chain steps would STOP MISSING_INPUT on a correct clone. Top-level *.json reports a step leaves in its
SAR_OUT_ROOT (run reports, STOP reports) are kept under STAGE_OUT/scratch_reports/ (except for a copy_frames
step, whose STAGE_OUT is the frames dir); they stay in the stage files on S3 and never reach summary.json.
Refuses off an R1 instance and without the sandbox marker <repo>/.r1_sandbox.json written for this config.
--plan prints every rendered argv and runs nothing.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import sys
import time

HOSTS = ("ec2-r1-test", "ec2-r1")
SCHEMA = "sar.r1.chain.v1"
NAME = re.compile(r"^[a-z0-9][a-z0-9_]{0,40}$")
ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
PLACEHOLDER = re.compile(r"\{([a-z]+)(?::([^{}]*))?\}")
RESERVED_ENV = {"SAR_R1_CONFIG", "SAR_OUT_ROOT", "PATH", "R_LIBS", "PYTHONHASHSEED", "SAR_HOST"}
STEP_KEYS = {"name", "argv", "writes"}
OPTIONAL_KEYS = {"configs", "env", "post", "frames_dir", "source"}
POSTS = ("copy_frames",)
MARKER = ".r1_sandbox.json"


def stop(code, detail) -> None:
    raise SystemExit(f"run_config: STOP {code}: {detail}")


def sha256_file(p) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def digest_of(path):
    """run_stages.digest_of: a file's sha256, or the sha256 of a directory's sorted '<sha>  <rel>' lines; None if absent."""
    path = pathlib.Path(path)
    if path.is_file():
        return sha256_file(path)
    if not path.is_dir():
        return None
    rows = sorted((p.relative_to(path).as_posix(), sha256_file(p)) for p in path.rglob("*") if p.is_file())
    return hashlib.sha256("".join(f"{s}  {r}\n" for r, s in rows).encode()).hexdigest()


def _rel_ok(p) -> bool:
    return isinstance(p, str) and p and not p.startswith("/") and ".." not in p.split("/")


def load_chain(path) -> dict:
    try:
        c = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        stop("BAD_CHAIN", f"{path}: {e}")
    if c.get("schema") != SCHEMA or not isinstance(c.get("steps"), list) or not c["steps"]:
        stop("BAD_CHAIN", f"{path}: not a {SCHEMA} chain")
    if not isinstance(c.get("b0_chain_paths"), list) or not all(_rel_ok(p) for p in c["b0_chain_paths"]):
        stop("BAD_CHAIN", "b0_chain_paths must be a list of repo-relative paths")
    seen = set()
    for s in c["steps"]:
        name = s.get("name")
        if not isinstance(name, str) or not NAME.match(name) or name in seen:
            stop("BAD_CHAIN", f"bad or duplicate step name {name!r}")
        seen.add(name)
        miss, extra = STEP_KEYS - set(s), set(s) - STEP_KEYS - OPTIONAL_KEYS
        if miss or extra:
            stop("BAD_CHAIN", f"step {name}: missing {sorted(miss)}, unknown {sorted(extra)}")
        if not isinstance(s["argv"], list) or not s["argv"] or not all(
                isinstance(a, list) and a and all(isinstance(x, str) for x in a) for a in s["argv"]):
            stop("BAD_CHAIN", f"step {name}: argv must be a non-empty list of non-empty string lists")
        if not isinstance(s["writes"], list) or not all(_rel_ok(w) for w in s["writes"]):
            stop("BAD_CHAIN", f"step {name}: writes must be repo-relative paths")
        env = s.get("env", {})
        if not isinstance(env, dict) or not all(isinstance(k, str) and ENV_NAME.match(k) and isinstance(v, str)
                                                for k, v in env.items()):
            stop("BAD_CHAIN", f"step {name}: env must map NAME -> string")
        if set(env) & RESERVED_ENV:
            stop("BAD_CHAIN", f"step {name}: env may not set {sorted(set(env) & RESERVED_ENV)}")
        if not set(s.get("configs", ["B0"])) <= {"B0", "M"}:
            stop("BAD_CHAIN", f"step {name}: configs must be B0 and/or M")
        if "post" in s and s["post"] not in POSTS:
            stop("BAD_CHAIN", f"step {name}: unknown post {s['post']!r}")
        if (s.get("post") == "copy_frames") != ("frames_dir" in s) or (
                "frames_dir" in s and s["frames_dir"] not in s["writes"]):
            stop("BAD_CHAIN", f"step {name}: copy_frames needs a frames_dir that is one of its writes")
    return c


CONFIG_SCHEMA = "sar.r1.run_config.v1"
SCRATCH_REPORT_MAX = 20 << 20      # bytes: a scratch report above this stays behind


class Config:
    """The run config a step names: its name and sha256 at once; the full loader only when a value is needed."""

    def __init__(self, path):
        self.path = pathlib.Path(path).resolve()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            stop("BAD_CONFIG", f"{path}: {e}")
        if not isinstance(raw, dict) or raw.get("schema") != CONFIG_SCHEMA or raw.get("config") not in ("B0", "M"):
            stop("BAD_CONFIG", f"{path}: not a {CONFIG_SCHEMA} file for B0 or M")
        self.name = raw["config"]
        self.sha256 = sha256_file(self.path)
        self._loaded = None

    def loaded(self):
        """(r1_config.RunConfig, the r1_config module), through pipeline/lib/r1_config.py of the config's repo."""
        if self._loaded is None:
            repo = self.path.parents[2] if len(self.path.parents) > 2 else self.path.parent
            if not (repo / "pipeline" / "lib" / "r1_config.py").is_file():
                stop("BAD_CONFIG", f"{self.path} is not <repo>/config/r1/<name>.json")
            if str(repo) not in sys.path:
                sys.path.insert(0, str(repo))
            r1c = importlib.import_module("pipeline.lib.r1_config")
            try:
                self._loaded = (r1c.load(self.path, repo=repo), r1c)
            except r1c.ConfigStop as e:
                stop("CONFIG", f"{getattr(e, 'code', '')} {e}".strip())
        return self._loaded

    def value(self, arg):
        """{cfg:SECTION.KEY}: the section's resolved value (repo:/work: tokens as paths), or None."""
        cfg, r1c = self.loaded()
        section, _, key = arg.partition(".")
        if not key:
            return None
        try:
            return cfg.resolved(section).get(key)
        except (AttributeError, TypeError, r1c.ConfigStop):
            return None


def render(text, ctx, cfg, *, step) -> list:
    """One argv item (or env value) with its placeholders filled; a list value fills a whole item only."""
    out, pos = [], 0
    whole = PLACEHOLDER.fullmatch(text)
    for m in PLACEHOLDER.finditer(text):
        kind, arg = m.group(1), m.group(2)
        if kind == "cfg" and arg:
            val = cfg.value(arg)
            if val is None:
                stop("MISSING_KEY", f"step {step}: the config has no value for {arg!r}")
        elif kind in ctx and arg is None:
            val = ctx[kind]
        else:
            stop("PLACEHOLDER", f"step {step}: unknown placeholder {m.group(0)!r}")
        if isinstance(val, (list, tuple)):
            if not whole:
                stop("PLACEHOLDER", f"step {step}: list value {m.group(0)!r} must fill a whole argument")
            return [str(v) for v in val]
        if isinstance(val, dict):
            stop("PLACEHOLDER", f"step {step}: {m.group(0)!r} is a section, not a value")
        out.append(text[pos:m.start()] + str(val))
        pos = m.end()
    return ["".join(out) + text[pos:]]


def rendered(step, ctx, cfg) -> tuple[list, dict]:
    argv = [[x for item in a for x in render(item, ctx, cfg, step=step["name"])] for a in step["argv"]]
    env = {k: render(v, ctx, cfg, step=step["name"])[0] for k, v in step.get("env", {}).items()}
    return argv, env


def keep_scratch_reports(sar_out, dst) -> list:
    """Top-level *.json files of the step's SAR_OUT_ROOT (run / STOP reports) into dst; returns their names."""
    kept = []
    for p in sorted(pathlib.Path(sar_out).glob("*.json")):
        if p.is_file() and not p.is_symlink() and p.stat().st_size <= SCRATCH_REPORT_MAX:
            dst.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, dst / p.name)
            kept.append(p.name)
    return kept


def copy_frames(src, dst) -> dict:
    src, dst = pathlib.Path(src), pathlib.Path(dst)
    if not (src / "MANIFEST.sha256").is_file():
        stop("NO_MANIFEST", f"{src} has no MANIFEST.sha256")
    files = sorted(src.iterdir())
    if any(not p.is_file() for p in files):
        stop("COPY_FRAMES", f"{src} holds a non-file entry")
    dst.mkdir(parents=True, exist_ok=True)
    for p in files:
        t = dst / p.name
        if t.exists():
            stop("COPY_FRAMES", f"{t} exists already")
        shutil.copyfile(p, t)
        if sha256_file(t) != sha256_file(p):
            stop("COPY_FRAMES", f"{t} is not a byte copy of {p}")
    return {"copied": len(files), "manifest_sha256": sha256_file(dst / "MANIFEST.sha256")}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="R1 run-config chain step")
    for k in ("--config", "--chain", "--repo", "--work"):
        ap.add_argument(k, required=True)
    ap.add_argument("--step")
    ap.add_argument("--out")
    ap.add_argument("--plan", action="store_true", help="print every rendered argv; run nothing")
    a = ap.parse_args(argv)
    if not a.plan and not (a.step and a.out):
        ap.error("--step and --out are required unless --plan")
    repo, work = pathlib.Path(a.repo), pathlib.Path(a.work)
    if not a.plan and os.environ.get("SAR_HOST", "").strip() not in HOSTS:
        raise SystemExit("R1 rule: run_config.py runs only on an R1 instance ($SAR_HOST)")
    chain = load_chain(a.chain)
    steps = {s["name"]: s for s in chain["steps"]}
    if a.step and a.step not in steps:
        stop("UNKNOWN_STEP", f"{a.step!r} is not a step of {a.chain}")
    cfg = Config(a.config)
    if a.step and cfg.name not in steps[a.step].get("configs", ["B0"]):
        stop("NOT_FOR_CONFIG", f"step {a.step} is not a step of config {cfg.name}")
    todo = [steps[a.step]] if a.step else [s for s in chain["steps"] if cfg.name in s.get("configs", ["B0"])]
    py = os.environ.get("PY") or sys.executable

    def ctx_of(s, out=None):
        return {"py": py, "repo": str(repo), "work": str(work), "out": str(out or work / "prod" / s["name"]),
                "tmp": str(work / "tmp" / s["name"])}

    if a.plan:
        cfg.loaded()                                  # a plan is the full check: every STOP rule of the loader
        for s in todo:
            argvs, env = rendered(s, ctx_of(s, a.out if a.step else None), cfg)
            print(f"## {s['name']}  (config {cfg.name}; writes {', '.join(s['writes']) or '-'}"
                  f"{'; post ' + s['post'] if s.get('post') else ''})")
            for k, v in sorted(env.items()):
                print(f"env {k}={shlex.quote(v)}")
            for x in argvs:
                print(shlex.join(x))
        return 0

    step = steps[a.step]
    mk = repo / MARKER
    try:
        marker = json.loads(mk.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        stop("NO_SANDBOX", f"{mk} is missing or unreadable: the sandbox stage has not purged this clone")
    if marker.get("config") != cfg.name:
        stop("NO_SANDBOX", f"{mk} was written for config {marker.get('config')!r}, not {cfg.name}")
    rscript = os.environ.get("SAR_RSCRIPT_RMAC", "").strip()
    if not rscript:
        stop("NO_RMAC", "no Mac R stack on this instance ($SAR_RSCRIPT_RMAC unset)")
    out = pathlib.Path(a.out)
    ctx = ctx_of(step, out)
    argvs, step_env = rendered(step, ctx, cfg)
    tmp = pathlib.Path(ctx["tmp"])
    if tmp.exists():
        shutil.rmtree(tmp)
    sar_out = tmp / "sar_out"
    sar_out.mkdir(parents=True)
    out.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, **step_env, SAR_R1_CONFIG=str(cfg.path), SAR_OUT_ROOT=str(sar_out),
               PATH=f"{os.path.dirname(rscript)}:{os.environ.get('PATH', '')}", PYTHONHASHSEED="0")
    if os.environ.get("SAR_RLIB_RMAC", "").strip():
        env["R_LIBS"] = os.environ["SAR_RLIB_RMAC"].strip()
    t0, rc, n = time.time(), 0, 0
    for x in argvs:
        n += 1
        print(f"[run_config] {step['name']} {n}/{len(argvs)}: {shlex.join(x)}", flush=True)
        rc = subprocess.run(x, cwd=repo, env=env).returncode
        if rc:
            break
    report = {"schema": "sar.r1.step_report.v1", "step": step["name"], "config": cfg.name,
              "config_sha256": cfg.sha256, "chain_sha256": sha256_file(a.chain), "rc": rc,
              "invocations": n, "secs": round(time.time() - t0, 1),
              "writes": {w: (digest_of(repo / w) if rc == 0 else None) for w in step["writes"]}}
    report["missing"] = [w for w, d in report["writes"].items() if d is None] if rc == 0 else []
    post_stop = None
    if rc == 0 and not report["missing"] and step.get("post") == "copy_frames":
        try:
            report["post"] = copy_frames(repo / step["frames_dir"], work / "prod" / "frames")
        except SystemExit as e:
            post_stop, report["post"] = e, {"error": str(e)}
    if step.get("post") != "copy_frames":
        report["scratch_reports"] = keep_scratch_reports(sar_out, out / "scratch_reports")
    (out / "step_report.json").write_text(json.dumps(report, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    if post_stop is not None:
        raise post_stop
    if rc:
        print(f"[run_config] {step['name']}: invocation {n} exited {rc}", flush=True)
        return rc
    if report["missing"]:
        print(f"[run_config] {step['name']}: declared writes missing {report['missing']}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
