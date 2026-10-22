# Progress

Newest first. One entry per merged task or chunk.

## 2026-10-22 · The bill of materials lists every part, with gearing, voltage and EUR prices

`hardware/bom.md` now shows which gearing each joint of the leader and
follower needs, which servo voltage goes with which power supply (5 V or
12 V), the bus servo adapter board and indicative EUR prices from upstream.
It also explains why a wrong supply can burn out a servo. Parts the owner
still has to confirm are marked with #29. Links: issue #28.

## 2026-10-22 · One command finds the arm ports and fills in `local.yaml`

`uv run so101-find-ports` asks you to unplug and replug the leader and then
the follower arm, works out each arm's serial port from what disappeared, and
writes both to `configs/local.yaml` without touching the other keys. The file
is checked with the machine config validator before it is written, and
`--dry-run` prints the plan and changes nothing. It does not use
`lerobot-find-port`, which waits on the keyboard and saves nothing. Tested
with fake ports and fake key presses only; it has not been run on the real
arms yet.

## 2026-10-22 · Two calibrations can be compared joint by joint

`so101.diff_calibrations` compares two calibrations and lists, for each joint,
the old value, new value and change in `id`, `homing_offset`, `range_min`,
`range_max` and `drive_mode`, plus joints present in only one. `format_diff`
turns the result into a readable table. Tested on the follower's real
calibration and a slightly changed copy. No command-line tool yet; the issue
did not ask for one.

## 2026-10-22 · LeRobot commands are built from the machine config

`hw_setup.lerobot_argv` builds the `lerobot-setup-motors`,
`lerobot-calibrate`, `lerobot-teleoperate` and `lerobot-record` commands
from `configs/local.yaml`: the follower's port, id and cameras go to
`--robot.*`, the leader's to `--teleop.*`, and both read their calibration
from `hardware/calibration/<role>/`. The tests feed every command to
LeRobot 0.6.1's own argument parser, so a wrong flag name fails them.
Nothing was run on hardware.

## 2026-10-22 · Every source module has tests, 100% covered

Coverage rose from 93% to 100% (line and branch) across `so101` and
`hw-setup`; run it with `uv run pytest --cov`. The calibration checks now
have edge tests: gripper width 300 and 2500 pass, 250 and 3000 fail, and a
range of exactly 200 passes. A test also checks the installed LeRobot is
0.6.1. Nothing was run on hardware.

## 2026-10-22 · First arm calibrations are committed, and checked in CI

The owner's initial calibrations of the leader and follower arms are now in
`hardware/calibration/{leader,follower}/main.json`. A new test loads every
JSON under `hardware/calibration/` and runs the sanity checks, one test per
file, so a bad calibration commit turns CI red and names the file. Both files
pass. Nothing was run on hardware in this task.

## 2026-10-22 · Repo checked against the org standard

The repo was checked row by row against the org's repo standard. The task
issue template now uses the same headings as the board's issues and points at
the project board, and local Claude session files no longer show up as
untracked. The README status is refreshed.

## 2026-10-22 · Type stubs no longer installed with so101

`types-pyyaml` moved from `so101`'s runtime dependencies to the workspace dev
group, so installing `so101` pulls in only `pyyaml`. `uv run ty check` still
passes.

## 2026-10-22 · A bad calibration now names the joint

`so101.check_calibration` checks a calibration for inverted ranges, ranges
too narrow to be real, a gripper span outside what the gripper can do, and
motor ids that do not match the joint order (1 to 6). Every failure is listed
with the joint and the check that caught it. Nothing was run on hardware.

## 2026-10-22 · LeRobot installed in the workspace

The new `hw-setup` project pins `lerobot[feetech]==0.6.1`, so LeRobot's arm
tools now run from the workspace. `lerobot-calibrate --help` works. No
hardware has been connected yet.

## 2026-10-22 · Machine config is checked on load

`so101` can now read `configs/local.yaml` and check it: each arm needs an id
and a serial port that looks like one, and each camera needs an index, width,
height and fps, with no two cameras sharing an index. A wrong file gives an
error that names the key, such as `cameras.front.fps: missing`.
`configs/example.yaml` passes. Nothing opens a port or a camera.

## 2026-10-22 · Repo scaffolded for the SO-101 arm

There is now one place for everything about the SO-101 arms: a uv workspace
with a shared `so101` package, a copyable project template, and folders for
calibration files, URDF, CAD and the bill of materials. The shared package
can already read and check a LeRobot calibration file, so a bad or partial
calibration is caught before it reaches a servo. No hardware has been
connected yet.
