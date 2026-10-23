"""``so101-teleop``: start ``lerobot-teleoperate`` once both calibrations pass.

Before anything else it loads ``hardware/calibration/<role>/<id>.json`` for
the leader and the follower (the id comes from the machine config) and runs
``so101.check_calibration`` on each. If either file is missing or fails, it
names the arm and the problem and exits 1, also under ``--dry-run``.
``--dry-run`` otherwise prints the exact command and runs nothing.

Every command caps how far the follower moves per update
(``--robot.max_relative_target``, see ``hw_setup.lerobot_argv``). The default,
``DEFAULT_MAX_STEP`` = 5.0, is 5 degrees per update for the body joints and
5 % of the calibrated range for the gripper. It is the value used on the real
arms on 2026-10-22. At LeRobot's default 60 Hz teleop loop (30 Hz when
recording) it still allows 300 (150) degrees per second, faster than the arm
is moved by hand, so normal teleop is not slowed; what it stops is a single
update jumping the full distance to a far-away leader pose. ``--max-step
none`` passes ``null`` and prints a warning.

Then, unless ``--skip-align`` (which warns), ``hw_setup.align`` connects
both arms read-only and refuses with exit 1 and a per-joint table when any
joint differs by more than ``--align-max`` (default 5: degrees for body
joints, % of range for the gripper). ``--dry-run`` does not connect; it says
the check would run.
"""

import argparse
import math
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from hw_setup import align
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

DEFAULT_MAX_STEP = 5.0
NO_CAP_WARNING = (
    "WARNING: --max-step none: no movement cap. The follower will move as far "
    "as the leader asks in a single update."
)


def max_step(text: str) -> float | None:
    """``--max-step``: a positive number, or ``none`` for no cap."""
    if text.strip().lower() == "none":
        return None
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"expected a number or 'none', got {text!r}"
        ) from None
    if not (math.isfinite(value) and value > 0):
        raise argparse.ArgumentTypeError(f"must be more than 0, got {text!r}")
    return value


def add_max_step_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--max-step",
        type=max_step,
        default=DEFAULT_MAX_STEP,
        help="largest follower move per update: degrees for the body joints, "
        f"%% of range for the gripper (default: {DEFAULT_MAX_STEP}); "
        "'none' removes the cap",
    )


def describe_max_step(value: float | None, prog: str) -> str:
    """The line printed before the command; warns on stderr for no cap."""
    if value is None:
        print(f"{prog}: {NO_CAP_WARNING}", file=sys.stderr)
        return "Movement cap: none (--max-step none)"
    return (
        f"Movement cap: {value} per update "
        "(degrees for body joints, % of range for the gripper)"
    )


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
        except OSError as err:  # for example permissions 000
            problems.append(
                f"{role.value} arm ({arm_id}): calibration cannot be read: "
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
    add_max_step_argument(parser)
    align.add_align_arguments(parser)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="check calibrations, print the command; does not connect to the arms",
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
    device_factory: align.DeviceFactory | None = None,
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
            config,
            workspace,
            max_relative_target=args.max_step,
            cameras=args.cameras,
            display_data=args.display,
        )
    except (WorkspaceError, ValueError) as err:
        print(f"so101-teleop: {err}", file=sys.stderr)
        return 1

    print("Calibration checked: leader and follower pass.")
    refused = align.alignment_gate(
        config,
        workspace,
        limit=args.align_max,
        skip=args.skip_align,
        dry_run=args.dry_run,
        prog="so101-teleop",
        device_factory=device_factory,
    )
    if refused is not None:
        return refused
    print(describe_max_step(args.max_step, "so101-teleop"))
    print(f"Command: {format_command(command)}")
    if args.dry_run:
        print("Dry run: nothing was run.")
        return 0
    return runner(command)


def cli() -> None:
    sys.exit(main())
