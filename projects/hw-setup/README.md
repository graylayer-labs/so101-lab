# hw-setup

Gets the SO-101 arms ready for use: finds their serial ports, sets motor IDs
and calibrates them with LeRobot's tools, run from this workspace.

## Goal

LeRobot is installed in the workspace and the arm tools run from it.

## Expected results

`uv run lerobot-calibrate --help` exits 0. Success is exit code 0; failure is
any import or install error.

## Status (2026-10-22)

- Done: `lerobot[feetech]==0.6.1` pinned and installed; LeRobot commands
  built from the machine config (`hw_setup.lerobot_argv`).
- Done: `so101-setup-motors` (guided motor setup, `--dry-run`).
- Done: `so101-teleop` (calibration-gated teleoperation, `--dry-run`).
- Doing: nothing.
- Done: `so101-find-ports` (tested with fakes; not yet run on hardware).
- Done: `so101-calibrate` (tested with fakes; not yet run on hardware).
- Next: set motor IDs (needs hardware).

## Find the ports

```bash
uv run so101-find-ports --dry-run   # print the plan; touches nothing
uv run so101-find-ports             # needs both arms plugged in
```

For the leader and then the follower arm it asks you to unplug the USB cable,
then plug it back in, and takes the port that disappeared. It lists ports with
pyserial, which does not open them. It then writes `arms.leader.port` and
`arms.follower.port` to `configs/local.yaml` (created from
`configs/example.yaml` if missing), keeps the other keys, and refuses to write
a file that fails `so101.machine_config`. Comments in an existing
`local.yaml` are not kept. With no `--config` it uses `<workspace root>/configs/local.yaml`, found by
looking upward for `configs/example.yaml`, so it works from any subfolder.
If an arm does not come back after the replug, plug it into the same USB
socket: the macOS port name depends on the socket.

This does not call `lerobot-find-port`: that tool blocks on `input()`,
globs `/dev/tty*` and writes nothing, so it cannot be tested or scripted.

## Calibrate an arm

```bash
uv run so101-calibrate --role follower --dry-run   # print the plan; touches nothing
uv run so101-calibrate --role follower             # needs the arm plugged in
```

It runs `lerobot-calibrate` for one arm (`--role leader` or `follower`) with
`calibration_dir` set to `hardware/calibration/<role>`, so the result lands in
`hardware/calibration/<role>/<id>.json`, with `<id>` from
`configs/local.yaml` (or `--config PATH`).

- Before the run, an existing file is copied to
  `hardware/calibration/<role>/backups/<id>.<UTC time>.json.bak`. LeRobot only
  reads `<id>.json`, and the `.bak` suffix keeps backups out of the CI check
  on every `*.json`. The `backups/` folders are gitignored.
- When the file exists, LeRobot asks first: type `c` and press ENTER to
  recalibrate. Anything other than `c` keeps the existing file; the script
  then says the file is unchanged and removes the identical backup.
- An existing file that cannot be loaded is refused before LeRobot runs,
  because LeRobot would crash loading it. The error prints the `mv` command
  that moves it to the backup path; `--move-corrupt` does that move and
  calibrates from scratch.
- Ctrl-C during the run (exit 130) or a LeRobot error prints the backup path
  and the `cp` command to restore it, since the file may be half-written.
- After the run, the new file is loaded, checked with
  `so101.check_calibration`, and compared with the old one per joint.
- First calibration (no file yet): no backup and no diff, and it says so.
- A failed check exits 1 and prints where the backup is and the `cp` command
  to restore it. Nothing is restored automatically: the motors already hold
  the new values, and the checks may be wrong for your arm. After a restore,
  LeRobot notices the file and motors differ on the next connect and asks to
  write the file to the motors.

## LeRobot commands

`hw_setup.lerobot_argv` turns the machine config into LeRobot command lines.
Each builder returns a `list[str]` and runs nothing; `format_command` joins
one into a line to paste into a shell.

```python
from pathlib import Path

from hw_setup.lerobot_argv import calibrate_argv, format_command
from so101 import ArmRole, load_machine_config

repo = Path(".")
config = load_machine_config(repo / "configs" / "local.yaml")
print(format_command(calibrate_argv(config, ArmRole.LEADER, repo.resolve())))
# lerobot-calibrate --teleop.type=so101_leader --teleop.port=/dev/tty.usbmodem...
#   --teleop.id=main --teleop.calibration_dir=<repo>/hardware/calibration/leader
```

- `setup_motors_argv` and `calibrate_argv` take one arm (`ArmRole`).
- `teleoperate_argv` and `record_argv` use both arms and the cameras.
  `record_argv` takes the dataset `repo_id`, `single_task` and
  `num_episodes`, plus optional `dataset_root`, `episode_time_s`,
  `reset_time_s`, `fps` and `push_to_hub`. Options left out use LeRobot's
  defaults, and LeRobot pushes to the Hub by default.
- The follower goes to `--robot.*`, the leader to `--teleop.*`.
  `calibration_dir` points at `hardware/calibration/<role>`, where LeRobot
  reads `<id>.json`.
- The flag names were checked against lerobot 0.6.1; the module docstring
  lists the source file and line of each.
- `lerobot-record` needs `lerobot[dataset]`, which is not installed yet:
  the record command can be built and printed but not run.

## Set the motor IDs

```bash
uv run so101-setup-motors --role leader --dry-run   # show everything, run nothing
uv run so101-setup-motors --role follower           # asks, then runs LeRobot
```

Before it runs anything it prints the wiring order (gripper first, one motor
on the controller board at a time), the gear ratio of each joint (leader
1/191 on joints 1 and 3, 1/345 on 2, 1/147 on 4 to 6; follower 1/345 on all)
and the power warning (the leader always uses 5 V; the follower uses 5 V, or
12 V with 12 V servos). Then it asks `y` to continue; anything else exits 1.
`--dry-run` also prints the exact command and exits 0 without asking.
`--config PATH` overrides the default `configs/local.yaml` in the workspace
root, which is found from the package, not the current directory. If that
file is missing the command fails with a hint; it never uses the example.
## Teleoperate

```bash
uv run so101-teleop --dry-run            # check calibrations, print the command
uv run so101-teleop --no-cameras         # leader drives follower, no cameras
uv run so101-teleop --display            # also show the data live
```

First it checks `hardware/calibration/<role>/<id>.json` for both arms (the id
is from the machine config) with `so101.load_calibration` and
`so101.check_calibration`. If either file is missing or fails, it prints the
arm and the problem to stderr and exits 1; this also applies to `--dry-run`.
Then it runs `lerobot-teleoperate` (or, with `--dry-run`, prints the exact
command and exits 0). Cameras are on by default; `--config PATH` overrides
`configs/local.yaml` in the workspace root, which has no fallback to the
example.

## Layout

- `src/hw_setup/`: the code.
- `tests/`: tests for it.
- `configs/`: run configs for this project. Machine settings (ports, cameras)
  stay in the root `configs/`.

## Run

```bash
uv sync --dev --all-packages
uv run pytest projects/hw-setup
```
