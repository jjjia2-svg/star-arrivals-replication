#!/usr/bin/env bash
# pipeline/aws/launch_p3_dcdh.sh — the EC2 launch for the four Panel-3 cells that were estimated in
# the cloud. DOCUMENTATION. It prints the runbook and exits; it cannot start an instance.
#
# Why it prints instead of runs: everything below costs money on someone else's account, and the
# four cells it would recompute are already frozen in data/estimates/ with a chain of custody that
# `tools/verify_cloud_custody.py` checks in seconds (input md5 == what was shipped, output JSON ==
# the frozen result). Re-running is a decision for the author, made deliberately, with the AWS
# identity and the security group of whoever is doing it — none of which this package can supply.
set -euo pipefail
cat <<'RUNBOOK'
================================================================================
 P3 dCDH cloud cells — runbook (documentation; nothing here is executed)
================================================================================

WHAT RAN THERE, AND WHY IT COULD NOT RUN HERE
  Four Panel-3 cells over 12.2 M (economics) and 4.5 M (chemistry) pair-years. The
  dCDH estimator materialises the whole panel; the measured peak was 305 GiB for
  the economics main cell, so a 512 GiB machine is the requirement, not a luxury.
  Everything else in this package runs on a laptop.

    run                        cell                    wall     peak RSS
    p3_main_2026-08-16         P3_fnfix_chemistry      1:47     91.1 GiB
    p3_main_2026-08-16         P3_econ_fnfix           5:34    289.4 GiB
    p3_evcl_2026-08-16         P3evcl_chemistry        2:09     96.4 GiB
    p3_evcl_2026-08-16         P3evcl_econ            6:55    304.9 GiB

INSTANCE
  type      r6i.16xlarge      64 vCPU, 512 GiB RAM
  region    us-east-1
  image     ami-052355af2a014bd2c   (Ubuntu 24.04 LTS "noble", x86_64)
  storage   100 GiB gp3 root; no instance store is used
  fuse      user-data is `#!/bin/bash` + `shutdown -h +600` — a ten-hour hard stop
            so a forgotten instance cannot bill past it

COST AND RUNTIME (measured, from the run records in this directory)
  p3_main   launched 2026-08-15T18:15:52Z, terminated 18:37:23Z  = 21m31s billed
  p3_evcl   launched 2026-08-16T09:09:51Z, terminated 09:34:00Z  = 24m09s billed
  r6i.16xlarge on-demand in us-east-1 was about $4.03/h at the time, so each run
  was roughly $1.50. Budget $5 for both and a $100 account budget alarm; the
  author's runs stayed inside it. Prices change — check before you launch.

LAUNCH (the command the author ran; reproduced here as text, not as code)
  IID=$(aws ec2 run-instances --region us-east-1 \
    --image-id ami-052355af2a014bd2c --instance-type r6i.16xlarge \
    --key-name <your key> --security-group-ids <your sg> \
    --block-device-mappings '[{"DeviceName":"/dev/sda1","Ebs":{"VolumeSize":100,"VolumeType":"gp3"}}]' \
    --user-data file://userdata.txt \
    --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=p3-final},{Key=purpose,Value=chem-econ-P3-final}]' \
    --query "Instances[0].InstanceId" --output text)
  # userdata.txt is exactly two lines:  #!/bin/bash  /  shutdown -h +600

THEN, IN ORDER
  1. bootstrap   logs/p3_main_2026-08-16/bootstrap.sh
                 r2u for the CRAN binaries, then rustup + a source build of the R
                 polars package (there is no prebuilt binary; this is the recipe
                 that worked). It ends by printing PKG_OK and starting a memory
                 sentinel that appends `free -g` to ~/mem.log every 30 s.
  2. ship        scp the two slim parquets and run_p3.R, then `md5sum -c payload.md5`
                 ON THE INSTANCE. The driver refuses to start if that fails. The
                 payload hashes are in logs/*/payload.md5 and are the SAME bytes as
                 the frames in data/frames — `tools/verify_cloud_custody.py` proves it.
  3. run         logs/p3_main_2026-08-16/driver.sh — the two cells in sequence under
                 /usr/bin/time -v, each with its own exit marker, ending in
                 ALL_DONE_MARKER or FAIL_MARKER in ~/RESULT.txt.
  4. fetch       watch_and_fetch.sh polls RESULT.txt every ~5 minutes, salvages
                 out/*.json, mem.log, time_v.log and the driver log WHATEVER the
                 outcome, and only then terminates. Salvage before terminate is the
                 rule: an instance that dies with its logs on it teaches nothing.
  5. terminate   aws ec2 terminate-instances --region us-east-1 --instance-ids "$IID"
                 Confirm in the console. The 10-hour fuse is a backstop, not a plan.

WHAT IS IN THIS DIRECTORY
  logs/p3_main_2026-08-16/   bootstrap.sh, driver.sh, run_p3.R, payload.md5,
  logs/p3_evcl_2026-08-16/   launch/terminate timestamps, watcher.log, and fetch/
                             with the returned JSON and the full `time -v` output.

WHAT TO DO INSTEAD OF RUNNING THIS
  python3 tools/verify_cloud_custody.py     -> CUSTODY_OK
  It checks, for both runs: every shipped input is byte-identical to the frame in
  data/frames (md5 against payload.md5), and every JSON fetched back equals the
  frozen estimate in data/estimates. That is the whole claim these runs make.
================================================================================
RUNBOOK
