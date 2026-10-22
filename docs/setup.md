# Setup

Checklist from parts to a working leader-follower pair. Tick items as they
are done and note anything that differed from the upstream guide.

## Software

- [ ] Install [uv](https://docs.astral.sh/uv/) and run `uv sync --dev --all-packages`.
- [ ] `git lfs install` (once per machine, before adding CAD files).
- [ ] Copy `configs/example.yaml` to `configs/local.yaml`.
- [ ] Install LeRobot with the Feetech extra, in the first project that needs it.

## Parts

- [ ] Every row of [`hardware/bom.md`](../hardware/bom.md) filled in and received. Check each servo's voltage against its power supply first.
- [ ] Printed parts for both arms.

## Servos

- [ ] Find each controller board's port; write it to `configs/local.yaml`.
- [ ] Set servo ids 1 to 6 on the follower (joint order in `so101.JOINT_NAMES`).
- [ ] Set servo ids 1 to 6 on the leader.

## Assembly

- [ ] Follower assembled.
- [ ] Leader assembled.
- [ ] Cables routed so the full range of each joint is free.

## Calibration

- [ ] Follower calibrated; file in `hardware/calibration/follower/`.
- [ ] Leader calibrated; file in `hardware/calibration/leader/`.
- [ ] Both files load with `so101.load_calibration`.

## First motion

- [ ] Teleoperation: the follower tracks the leader.
- [ ] Cameras found and their indices in `configs/local.yaml`.
