"""``so101-teleop``: start ``lerobot-teleoperate`` once both calibrations pass.

Before anything else it loads ``hardware/calibration/<role>/<id>.json`` for
the leader and the follower (the id comes from the machine config) and runs
``so101.check_calibration`` on each. If either file is missing or fails, it
names the arm and the problem and exits 1, also under ``--dry-run``.
``--dry-run`` otherwise prints the exact command and runs nothing.
"""

import argparse
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from hw_setup.lerobot_argv import CALIBRATION_ROOT, format_command, teleoperate_argv
from hw_setup.workspace import WorkspaceError, find_workspace_root, load_local_config
from so101.arm import ArmRole
from so101.calibration import (
    CalibrationError,
    calibration_path,
    check_calibration,
    load_calibration,
)
from so101.machine_config import MachineConfig

Runner = Callable[[list[str]], int]


def _run(argv: list[str]) -> int:
    return subprocess.run(argv, check=False).returncode


def calibration_problems(config: MachineConfig, root: Path) -> list[str]:
    """One message per arm whose calibration file is missing or invalid."""
    problems = []
    for role in ArmRole:
        arm_id = config.arms[role].arm_id
        path = calibration_path(root / CALIBRATION_ROOT, role, arm_id)
        if not path.is_file():
            problems.append(f"{role.value} arm ({arm_id}): calibration missing: {path}")
            continue
        try:
            check_calibration(load_calibration(path))
        except CalibrationError as err:
            problems.append(f"{role.value} arm ({arm_id}): {err}")
        except ValueError as err:  # unreadable JSON
            problems.append(
                f"{role.value} arm ({arm_id}): calibration is not valid JSON: "
                f"{path}: {err}"
            )
    return problems


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="so101-teleop",
        description="Teleoperate the follower with the leader, if calibrated.",
    )
    parser.add_argument(
        "--cameras",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="pass the configured cameras to the follower (default: on)",
    )
    parser.add_argument(
        "--display", action="store_true", help="show the data live (--display_data)"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="check calibrations, print the command"
    )
    parser.add_argument(
        "--config", type=Path, help="machine config (default: configs/local.yaml)"
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    runner: Runner = _run,
    root: Path | None = None,
) -> int:
    args = _parser().parse_args(argv)
    try:
        workspace = root if root is not None else find_workspace_root()
        config = load_local_config(workspace, args.config)
        problems = calibration_problems(config, workspace)
        if problems:
            for problem in problems:
                print(f"so101-teleop: refusing to run: {problem}", file=sys.stderr)
            return 1
        command = teleoperate_argv(
            config, workspace, cameras=args.cameras, display_data=args.display
        )
    except (WorkspaceError, ValueError) as err:
        print(f"so101-teleop: {err}", file=sys.stderr)
        return 1

    print("Calibration checked: leader and follower pass.")
    print(f"Command: {format_command(command)}")
    if args.dry_run:
        print("Dry run: nothing was run.")
        return 0
    return runner(command)


def cli() -> None:
    sys.exit(main())
