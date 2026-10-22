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
- Doing: nothing.
- Next: find the ports and set motor IDs (needs hardware).

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
