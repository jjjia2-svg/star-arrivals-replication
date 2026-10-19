#!/usr/bin/env bash
# pipeline/aws/launch_u1_fetch.sh — the EC2 launch for the U1 full-snapshot fetch, the 17-hour step
# at the very top of this pipeline. DOCUMENTATION. It prints the runbook and exits.
#
# This is the one stage `pipeline/run_all.sh` does not offer at all, under any flag. It is not gated
# there, it is absent: it costs real money and 17 hours, its output is 15.4 GB of derived tables
# that live on the data disk rather than in this package, and nothing downstream can be checked
# against a rerun without also having that disk. What ships instead is this runbook plus the
# manifests the run produced, so a replicator can see exactly what was done and what it cost.
set -euo pipefail
cat <<'RUNBOOK'
================================================================================
 U1 full-snapshot fetch — runbook (documentation; nothing here is executed)
================================================================================

WHAT IT DOES
  Streams the frozen 2026-06-26 OpenAlex snapshot — 2,446 gzip works shards,
  510,372,821 records, about 694 GiB compressed — and writes the narrow tables
  every later stage reads: works, authorship edges, the person map, and the FWCI
  baseline population. Output ~15.4 GB across ~8,700 files.

INSTANCE (sizing is a decision, and the runbook says how it was made)
  Scanning time depends on snapshot BYTES, not on how many schools are in scope;
  what grows with scope is kept-works, and therefore ledger memory and reduce time.
  Worker ceiling = (RAM - ledger - 20 GiB headroom) / ~12 GiB peak per worker.

    peak memory <= 100 GiB   ->  i4i.4xlarge   16 vCPU / 128 GiB / 3.75 TB NVMe
    otherwise                ->  i4i.8xlarge   32 vCPU / 256 GiB / 2x3.75 TB
                                 (needs a vCPU quota of 32 — request it early)

  region  us-east-1 — the same region as the public `s3://openalex` bucket, so the
          700 GB pull is free. Out-of-region is the expensive mistake here.
  image   Ubuntu 24.04 LTS, resolved at launch rather than pinned:
          aws ssm get-parameters --names \
            /aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id \
            --query 'Parameters[0].Value' --output text
  root    30 GiB gp3. The snapshot goes on the NVMe instance store, mounted at
          /data — WHICH IS WIPED BY stop OR terminate. Products must be pushed to
          S3 as they are produced, not at the end.
  spot    NO. Interruption rate was over 20% and the instance store dies with the
          instance; only revisit once pass-B/C checkpointing is real and tested.

COST AND RUNTIME (measured, 2026-07-04, the two-school baseline)
  17h01m wall, 20.3 h billed, about $30 at $1.373/h for i4i.4xlarge.
  Memory peak 109 GiB with 83 GiB of swap; output 15.4 GB / 8,728 files.
  The 11-school run was extrapolated from this with a four-segment model, not a
  straight line. Check current prices; set an account budget alarm first.

LAUNCH (the command as it was run; text, not code)
  MYIP=$(curl -s ifconfig.me)
  aws ec2 authorize-security-group-ingress --group-id <sg> --protocol tcp --port 22 --cidr $MYIP/32
  AMI=$(aws ssm get-parameters --names \
     /aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id \
     --query 'Parameters[0].Value' --output text)
  IID=$(aws ec2 run-instances --image-id $AMI --instance-type i4i.4xlarge \
     --key-name <your key> --security-group-ids <sg> --iam-instance-profile Name=<role> \
     --block-device-mappings '[{"DeviceName":"/dev/sda1","Ebs":{"VolumeSize":30,"VolumeType":"gp3"}}]' \
     --query 'Instances[0].InstanceId' --output text)
  ssh ubuntu@$IP 'sudo mkfs.ext4 -L data /dev/nvme1n1 && sudo mkdir -p /data \
     && sudo mount /dev/nvme1n1 /data && sudo chown ubuntu /data && df -h /data'

THEN, IN ORDER
  1. environment  python3.12 venv with pyarrow==24.0.0 and duckdb==1.5.4 — the same
                  two versions this package pins. A 3.12 patch-level difference was
                  measured and the outputs stayed byte-identical.
  2. code         rsync the pipeline code only. No data, ever.
  3. tests        run the unit suite ON THE INSTANCE and require the same count as
                  locally. Anything red stops the run before it costs anything.
  4. snapshot     aws s3 sync s3://openalex/data/jsonl /data/openalex_pipeline/snapshot
                  --no-sign-request      (40-90 min, free in-region)
  5. verify       three checks, ALL must pass before anything else starts:
                    manifest.json sha256 prefix == da78e4b9b706d48d
                    works/*.gz count == the manifest's count (2,446)
                    no file under snapshot/ that is neither *.gz nor manifest.json
  6. run          the U1 driver under tmux, pushing products to S3 as they land.
  7. terminate    and check Cost Explorer the next day. The two-school baseline is
                  $30; a deviation over 50% should have an explanation.

WHAT TO DO INSTEAD OF RUNNING THIS
  Nothing downstream of this step needs it re-run. The FWCI scan's own manifest
  (data/fwci/scan_manifest.json, sha256-pinned in data/MANIFEST.sha256) records the
  record count, the shard count, zero bad lines and zero shard mismatches, and it is
  what the paper's funnel numbers are generated from — see analysis/paper/ledger_funnel.py
  and pipeline/NOT_REPRODUCIBLE.md.
================================================================================
RUNBOOK
