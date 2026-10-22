# Progress

Newest first. One entry per merged task or chunk.

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
