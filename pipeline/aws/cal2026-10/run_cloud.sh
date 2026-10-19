#!/usr/bin/env bash
# pipeline/aws/cal2026-10/run_cloud.sh — the RUNNABLE EC2 launcher for the October (cal2026-10)
# estimation cells. This is the one file in the repository that spends money; every `aws` call
# goes through aws_cli(), which prints instead of running under --dry-run.
#
#   bash run_cloud.sh --payload DIR --custody DIR [--dry-run] [--resume]
#                     [--key ~/.ssh/openalex-run.pem] [--key-name openalex-run]
#                     [--sg sg-047b8db2bb9452695] [--ami ami-052355af2a014bd2c]
#                     [--instance-type r6i.16xlarge] [--region us-east-1] [--root-gb 100]
#                     [--poll-secs 120] [--max-hours 9] [--tag cal2026-10]
#
# The payload dir is what `cloudkit.py prep` wrote (frames, R drivers, reference JSONs,
# bootstrap.sh, driver.sh, driver.env, jobs_*.txt, payload.md5). The custody dir receives every
# record of the run: state/ (the resumable step markers), watcher.log, userdata.txt,
# describe_launch.json, launch_time_utc.txt, md5check.log, fetch/ (everything under ~/work on the
# instance, whatever the outcome), termination_proof.json, terminate_time_utc.txt,
# launch_record.json, custody_cal2026-10.json.
#
# Sequence (each step is skipped when its marker in custody/state exists, so the script is
# idempotent and `--resume` continues an interrupted run against the same instance):
#   0 preflight   payload.md5 verified locally (cloudkit.py check-md5), aws cli + key present;
#                 --dry-run prints the plan and exits here, before anything is armed.
#   1 launch      ONE on-demand instance: AMI ami-052355af2a014bd2c (Ubuntu 24.04 noble, x86_64),
#                 r6i.16xlarge (64 vCPU / 512 GiB), us-east-1, key-name openalex-run,
#                 sg-047b8db2bb9452695, 100 GB gp3 root, user-data `shutdown -h +600` (the
#                 ten-hour hard fuse — the backstop when the plan below does not happen).
#                 The EXIT trap is armed HERE: from this line on, leaving the script for any
#                 reason (error, Ctrl-C, SIGTERM) salvages ~/work and terminates the instance.
#   2 ssh         wait for port 22 (BatchMode, no password prompts, own known_hosts file).
#   3 bootstrap   bootstrap.sh detached (nohup, stdin/stdout/stderr off the session — the 08-28
#                 hang), polled for work/bootstrap_ready.txt (PKG_OK inside, ~13 min).
#   4 ship        scp the payload dir to ~/work; `md5sum -c payload.md5` ON the instance; any
#                 FAILED line stops the run before the driver starts (08-16 rule).
#   5 driver      driver.sh detached; polled every --poll-secs: RESULT.txt, last driver.log and
#                 progress.log lines, last mem.log line -> watcher.log; --max-hours (< the fuse).
#   6 fetch       tar of ~/work (results, logs, timev, mem.log, versions.txt, bootstrap.log,
#                 md5check.log, driver.log, progress.log, RESULT.txt) -> custody/fetch, whatever
#                 the outcome: DONE, FAIL, TIMEOUT or an aborted step.
#   7 terminate   terminate-instances, wait, describe -> termination_proof.json; UTC times.
#   8 record      cloudkit.py record -> launch_record.json and the cost line
#                 (terminate - launch) x $4.032/h; cloudkit.py custody -> custody_cal2026-10.json.
# Exit status: 0 only when RESULT.txt carries ALL_DONE and the custody writer found no problem.
#
# Assumptions written down: the operator's AWS CLI is configured for the account that owns the key
# pair and security group above (this script never reads credentials); the AMI's login user is
# `ubuntu`; bash 3.2 (macOS /bin/bash) is enough — no arrays beyond "$@", no mapfile, no
# associative arrays; python3 = setup/.venv/bin/python when present (cloudkit.py needs only the
# standard library plus analysis/lib/compare_json.py). Two rules found by the 2026-09-22 review:
# every ssh/scp option is passed QUOTED through rssh()/rscp() — this checkout lived under a path
# with a space, and an unquoted option string word-split there so ssh took
# ".../known_hosts" as the host name and never reached the instance; and every `pgrep -f` pattern
# starts with a bracketed letter (`[b]ash driver.sh`) because procps pgrep does not exclude the
# invoking shell, whose command line carries the pattern text — with the plain pattern the
# "driver already running" probe always said yes and the driver was never started.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
PY="$REPO/setup/.venv/bin/python"; [ -x "$PY" ] || PY="$(command -v python3)"
KIT="$HERE/cloudkit.py"

PAYLOAD=""; CUSTODY=""; DRY_RUN=0; RESUME=0
KEY="$HOME/.ssh/openalex-run.pem"; KEY_NAME="openalex-run"
SG="sg-047b8db2bb9452695"; AMI="ami-052355af2a014bd2c"; ITYPE="r6i.16xlarge"
REGION="us-east-1"; ROOT_GB=100; POLL=120; MAX_HOURS=9; TAG="cal2026-10"
RATE="4.032"; SSH_USER="ubuntu"

usage() {
  sed -n '2,50p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-2}"
}
while [ $# -gt 0 ]; do
  case "$1" in
    --payload) PAYLOAD="$2"; shift 2 ;;
    --custody) CUSTODY="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    --resume) RESUME=1; shift ;;
    --key) KEY="$2"; shift 2 ;;
    --key-name) KEY_NAME="$2"; shift 2 ;;
    --sg) SG="$2"; shift 2 ;;
    --ami) AMI="$2"; shift 2 ;;
    --instance-type) ITYPE="$2"; shift 2 ;;
    --region) REGION="$2"; shift 2 ;;
    --root-gb) ROOT_GB="$2"; shift 2 ;;
    --poll-secs) POLL="$2"; shift 2 ;;
    --max-hours) MAX_HOURS="$2"; shift 2 ;;
    --tag) TAG="$2"; shift 2 ;;
    -h|--help) usage 0 ;;
    *) echo "unknown argument: $1" >&2; usage 2 ;;
  esac
done
[ -n "$PAYLOAD" ] && [ -n "$CUSTODY" ] || { echo "--payload and --custody are required" >&2; usage 2; }
# R1 (2026-10-13, N14): R1 jobs run only through pipeline/aws/r1/r1kit.py (one instance, no SSH, S3 writes
# under r1/); their run folders (data/cal2026-10r1/) are not shipped.
case "$TAG|$PAYLOAD|$CUSTODY" in
  *sar-r1*|*cal2026-10r1*) echo "R1 rule: this October launcher refuses R1 jobs; use pipeline/aws/r1/r1kit.py" >&2; exit 64 ;;
esac
PAYLOAD="$(cd "$PAYLOAD" 2>/dev/null && pwd)" || { echo "payload dir not found" >&2; exit 2; }
mkdir -p "$CUSTODY/state" "$CUSTODY/fetch"
CUSTODY="$(cd "$CUSTODY" && pwd)"
STATE="$CUSTODY/state"
WATCH="$CUSTODY/watcher.log"

now() { date -u +%FT%TZ; }
log() { echo "$(now) $*" | tee -a "$WATCH"; }
done_step() { [ -f "$STATE/$1" ]; }
mark() { echo "$(now) ${2:-}" > "$STATE/$1"; }
aws_cli() {
  if [ "$DRY_RUN" = 1 ]; then echo "[dry-run] aws --region $REGION $*"; return 0; fi
  aws --region "$REGION" "$@"
}
KNOWN_HOSTS="$CUSTODY/known_hosts"
rssh() { # rssh <cmd...>  — run on the instance (options quoted: $CUSTODY may contain a space)
  ssh -i "$KEY" -o BatchMode=yes -o StrictHostKeyChecking=no -o "UserKnownHostsFile=$KNOWN_HOSTS" \
      -o ConnectTimeout=10 -o ServerAliveInterval=30 "$SSH_USER@$IP" "$@"
}
rscp() { # rscp [-r] <src> <user@host:dest>  — copy to the instance, same options as rssh
  scp -i "$KEY" -o BatchMode=yes -o StrictHostKeyChecking=no -o "UserKnownHostsFile=$KNOWN_HOSTS" \
      -o ConnectTimeout=10 "$@"
}
IID=""; IP=""
[ -f "$STATE/instance_id" ] && IID="$(sed -n 1p "$STATE/instance_id")"
[ -f "$STATE/public_ip" ] && IP="$(sed -n 1p "$STATE/public_ip")"

# ---- 0 preflight --------------------------------------------------------------------------------
for f in payload.md5 bootstrap.sh driver.sh driver.env jobs_serial.txt jobs_parallel.txt; do
  [ -f "$PAYLOAD/$f" ] || { echo "payload incomplete: $PAYLOAD/$f missing (run cloudkit.py prep)" >&2; exit 1; }
done
echo "== local md5 check of $PAYLOAD (what the instance will repeat)"
"$PY" "$KIT" check-md5 "$PAYLOAD" || { echo "payload.md5 does not match the payload on disk — refusing to ship" >&2; exit 1; }
NSER=$(grep -c -v '^#' "$PAYLOAD/jobs_serial.txt" || true)
NPAR=$(grep -c -v '^#' "$PAYLOAD/jobs_parallel.txt" || true)
if [ -n "$IID" ] && [ "$RESUME" != 1 ] && [ "$DRY_RUN" != 1 ]; then
  echo "state in $CUSTODY names instance $IID from an earlier run; pass --resume to continue it or use a fresh --custody dir" >&2
  exit 1
fi
printf '#!/bin/bash\nshutdown -h +600\n' > "$CUSTODY/userdata.txt"
BDM="[{\"DeviceName\":\"/dev/sda1\",\"Ebs\":{\"VolumeSize\":$ROOT_GB,\"VolumeType\":\"gp3\"}}]"
TAGS="ResourceType=instance,Tags=[{Key=Name,Value=$TAG},{Key=purpose,Value=star-arrivals-cal2026-10}]"

if [ "$DRY_RUN" = 1 ]; then
  echo "== DRY RUN: nothing is launched. The plan:"
  echo "   instance   $ITYPE in $REGION, AMI $AMI, key-name $KEY_NAME, sg $SG, ${ROOT_GB} GB gp3 root"
  echo "   fuse       user-data: $(tr '\n' ' ' < "$CUSTODY/userdata.txt")"
  echo "   payload    $PAYLOAD ($(wc -l < "$PAYLOAD/payload.md5" | tr -d ' ') files in payload.md5; $NSER serial cells, $NPAR parallel units)"
  echo "   custody    $CUSTODY"
  echo "   poll       every ${POLL}s, give up after ${MAX_HOURS}h (fuse at 10h)"
  echo "   rate       \$$RATE/h -> cost line = (terminate - launch) x rate"
  if [ -f "$CUSTODY/custody_preflight.json" ]; then
    "$PY" - "$CUSTODY/custody_preflight.json" <<'PYE'
import json, sys
e = json.load(open(sys.argv[1]))["cost_estimate"]
print(f"   estimate   ~{e['wall_min_projected']:.0f} min ≈ ${e['cost_usd_projected_on_demand']:.2f} (A6)")
PYE
  fi
  aws_cli ec2 run-instances --image-id "$AMI" --instance-type "$ITYPE" --key-name "$KEY_NAME" \
    --security-group-ids "$SG" --block-device-mappings "$BDM" --user-data "file://$CUSTODY/userdata.txt" \
    --tag-specifications "$TAGS" --query "Instances[0].InstanceId" --output text
  aws_cli ec2 terminate-instances --instance-ids '<instance id>'
  echo "== DRY RUN OK"
  exit 0
fi

command -v aws >/dev/null || { echo "aws cli not found" >&2; exit 1; }
[ -r "$KEY" ] || { echo "ssh key $KEY not readable" >&2; exit 1; }

# ---- salvage + terminate on ANY exit once an instance exists ---------------------------------------
fetch_work() {
  [ -n "$IP" ] || return 0
  log "FETCH start"
  # one tar over ssh of whatever exists (a broken run never wrote some of these; `ls -d` keeps the
  # list to what is there, so the same line works with GNU and BSD tar)
  rssh "cd ~/work 2>/dev/null && tar czf - \$(ls -d out out_perm out_null out_predate out_predate_control logs timev driver.log driver.out progress.log RESULT.txt md5check.log versions.txt mem.log bootstrap.log bootstrap_ready.txt 2>/dev/null)" \
    | tar xzf - -C "$CUSTODY/fetch" 2>/dev/null || log "FETCH partial (some files missing on the instance)"
  log "FETCH end: $(find "$CUSTODY/fetch" -type f | wc -l | tr -d ' ') files"
  mark fetched
}
terminate_now() {
  [ -n "$IID" ] || return 0
  done_step terminated && return 0
  log "TERMINATE $IID"
  aws_cli ec2 terminate-instances --instance-ids "$IID" > "$CUSTODY/terminate_call.json" || log "terminate-instances call FAILED — check the console NOW"
  aws_cli ec2 wait instance-terminated --instance-ids "$IID" || log "wait instance-terminated timed out"
  aws_cli ec2 describe-instances --instance-ids "$IID" \
    --query "Reservations[0].Instances[0].{InstanceId:InstanceId,State:State,StateTransitionReason:StateTransitionReason,InstanceType:InstanceType,Placement:Placement.AvailabilityZone,LaunchTime:LaunchTime}" \
    --output json > "$CUSTODY/termination_proof.json" || true
  now > "$CUSTODY/terminate_time_utc.txt"
  log "TERMINATED $IID state=$(grep -o '"Name": *"[a-z-]*"' "$CUSTODY/termination_proof.json" 2>/dev/null | head -1)"
  mark terminated "$IID"
}
on_exit() {
  rc=$?
  trap - EXIT
  if [ -n "$IID" ] && ! done_step terminated; then
    log "EXIT rc=$rc with instance $IID alive — salvage then terminate"
    fetch_work || true
    terminate_now || true
  fi
  if [ -n "$IID" ] && [ -f "$CUSTODY/terminate_time_utc.txt" ]; then
    "$PY" "$KIT" record --custody "$CUSTODY" --rate "$RATE" | tee -a "$WATCH" || true
  fi
  exit "$rc"
}

# ---- 1 launch -----------------------------------------------------------------------------------
if ! done_step launched; then
  log "LAUNCH $ITYPE $REGION ami=$AMI sg=$SG key=$KEY_NAME root=${ROOT_GB}G"
  IID="$(aws_cli ec2 run-instances --image-id "$AMI" --instance-type "$ITYPE" --key-name "$KEY_NAME" \
    --security-group-ids "$SG" --block-device-mappings "$BDM" --user-data "file://$CUSTODY/userdata.txt" \
    --tag-specifications "$TAGS" --query "Instances[0].InstanceId" --output text)"
  [ -n "$IID" ] && [ "$IID" != "None" ] || { echo "run-instances returned no instance id" >&2; exit 1; }
  echo "$IID" > "$STATE/instance_id"
  trap on_exit EXIT INT TERM
  aws_cli ec2 wait instance-running --instance-ids "$IID"
  aws_cli ec2 describe-instances --instance-ids "$IID" \
    --query "Reservations[0].Instances[0].{InstanceId:InstanceId,InstanceType:InstanceType,ImageId:ImageId,Placement:Placement,LaunchTime:LaunchTime,PublicIpAddress:PublicIpAddress,State:State}" \
    --output json > "$CUSTODY/describe_launch.json"
  IP="$(aws_cli ec2 describe-instances --instance-ids "$IID" --query "Reservations[0].Instances[0].PublicIpAddress" --output text)"
  echo "$IP" > "$STATE/public_ip"
  LT="$(aws_cli ec2 describe-instances --instance-ids "$IID" --query "Reservations[0].Instances[0].LaunchTime" --output text)"
  echo "$LT" | sed 's/\.[0-9]*Z$/Z/' > "$CUSTODY/launch_time_utc.txt"
  log "LAUNCHED $IID $ITYPE on-demand $(cat "$CUSTODY/launch_time_utc.txt") ip=$IP"
  mark launched "$IID"
else
  trap on_exit EXIT INT TERM
  log "RESUME $IID ip=$IP"
fi

# ---- 2 ssh ---------------------------------------------------------------------------------------
if ! done_step ssh_up; then
  i=0
  until rssh true 2>/dev/null; do
    i=$((i + 1)); [ "$i" -le 60 ] || { log "SSH never came up"; exit 1; }
    sleep 10
  done
  log "SSH_UP"; mark ssh_up
fi

# ---- 3 bootstrap ---------------------------------------------------------------------------------
if ! done_step bootstrapped; then
  if rssh 'test -f ~/work/bootstrap_ready.txt' 2>/dev/null; then
    log "BOOTSTRAP already done on the instance"
  else
    rscp "$PAYLOAD/bootstrap.sh" "$SSH_USER@$IP:~/bootstrap.sh"
    rssh 'mkdir -p ~/work && nohup bash ~/bootstrap.sh > ~/work/bootstrap.log 2>&1 < /dev/null &'
    log "BOOTSTRAP started"
    i=0
    until rssh 'test -f ~/work/bootstrap_ready.txt' 2>/dev/null; do
      i=$((i + 1)); [ "$i" -le 120 ] || { log "BOOTSTRAP timeout (40 min) — see fetch/bootstrap.log"; exit 1; }
      sleep 20
      # the script exited without writing its ready file: a failed apt/rustup/polars step
      if ! rssh 'pgrep -f "[b]ash .*bootstrap.sh" >/dev/null || test -f ~/work/bootstrap_ready.txt' 2>/dev/null; then
        log "BOOTSTRAP died before PKG_OK — see fetch/bootstrap.log"; exit 1
      fi
    done
  fi
  log "BOOTSTRAP_DONE $(rssh 'sed -n 1p ~/work/versions.txt' 2>/dev/null || true)"
  mark bootstrapped
fi

# ---- 4 ship + md5 on the instance ---------------------------------------------------------------
if ! done_step md5_ok; then
  rscp -r "$PAYLOAD/." "$SSH_USER@$IP:~/work/"
  rssh 'cd ~/work && md5sum -c payload.md5' > "$CUSTODY/md5check.log" 2>&1 || {
    log "PAYLOAD md5 FAILED on the instance:"; cat "$CUSTODY/md5check.log" | tee -a "$WATCH"; exit 1; }
  NOK=$(grep -c ': OK$' "$CUSTODY/md5check.log" || true)
  NLIST=$(grep -c . "$PAYLOAD/payload.md5" || true)
  [ "$NOK" = "$NLIST" ] || { log "md5 OK lines $NOK != listed $NLIST"; exit 1; }
  log "PAYLOAD_SHIPPED_MD5_OK $NOK/$NLIST"
  mark md5_ok
fi

# ---- 5 driver ------------------------------------------------------------------------------------
if ! done_step driver_started; then
  if rssh 'test -f ~/work/RESULT.txt || pgrep -f "[b]ash driver.sh" >/dev/null' 2>/dev/null; then
    log "DRIVER already running or finished on the instance"
  else
    rssh 'cd ~/work && nohup bash driver.sh > driver.out 2>&1 < /dev/null &'
    log "DRIVER_STARTED"
  fi
  mark driver_started
fi

RESULT=""
if ! done_step run_done; then
  DEADLINE=$(( $(date +%s) + MAX_HOURS * 3600 ))
  n=0
  while :; do
    n=$((n + 1))
    RESULT="$(rssh 'cat ~/work/RESULT.txt 2>/dev/null' 2>/dev/null || true)"
    LAST="$(rssh 'tail -n 1 ~/work/progress.log 2>/dev/null; tail -n 1 ~/work/driver.log 2>/dev/null; tail -n 1 ~/work/mem.log 2>/dev/null' 2>/dev/null | tr '\n' ' ' || true)"
    log "[poll $n] result='$RESULT' $LAST"
    [ -n "$RESULT" ] && break
    if [ "$(date +%s)" -ge "$DEADLINE" ]; then log "TIMEOUT after ${MAX_HOURS}h — salvaging"; break; fi
    sleep "$POLL"
  done
  mark run_done "$RESULT"
fi
RESULT="${RESULT:-$(sed -n 1p "$STATE/run_done" | cut -d' ' -f2- || true)}"

# ---- 6/7/8 fetch, terminate, record, custody ---------------------------------------------------
fetch_work
terminate_now
trap - EXIT INT TERM
"$PY" "$KIT" record --custody "$CUSTODY" --rate "$RATE" | tee -a "$WATCH"
GOLD=""
if "$PY" "$KIT" custody --custody "$CUSTODY" --payload "$PAYLOAD" $GOLD | tee -a "$WATCH"; then
  log "CUSTODY_OK result='$RESULT'"
  case "$RESULT" in ALL_DONE_MARKER_*) exit 0 ;; *) log "run did not reach ALL_DONE"; exit 3 ;; esac
else
  log "CUSTODY_PROBLEMS — see custody_cal2026-10.json; the fetched files are in $CUSTODY/fetch"
  exit 4
fi
