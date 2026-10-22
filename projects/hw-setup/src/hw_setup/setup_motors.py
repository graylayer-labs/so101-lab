"""``so101-setup-motors``: guided ``lerobot-setup-motors`` for one arm.

Prints the wiring order, the gear ratio per joint and the power warning, asks
for confirmation, then runs LeRobot's command. ``--dry-run`` prints the same
and the exact command, and stops there.

LeRobot's own script walks the motors in reverse (gripper first) and asks you
to connect one motor at a time (lerobot 0.6.1,
robots/so_follower/so_follower.py ``setup_motors``). The gear ratios are from
hardware/bom.md (source: the LeRobot SO-101 guide).
"""

import argparse
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from hw_setup.lerobot_argv import format_command, setup_motors_argv
from hw_setup.workspace import WorkspaceError, find_workspace_root, load_local_config
from so101.arm import JOINT_NAMES, ArmRole

# Gear reduction (the N in 1/N) per joint, in motor-id order (1 to 6).
GEAR_RATIOS: dict[ArmRole, tuple[int, ...]] = {
    ArmRole.LEADER: (191, 345, 191, 147, 147, 147),
    ArmRole.FOLLOWER: (345,) * 6,
}

Runner = Callable[[list[str]], int]
InputFn = Callable[[str], str]


def _run(argv: list[str]) -> int:
    return subprocess.run(argv, check=False).returncode


def power_warning(role: ArmRole) -> str:
    if role is ArmRole.LEADER:
        return "Power: the leader always uses 5 V."
    return (
        "Power: the follower uses a 5 V supply, or 12 V if it has 12 V servos. "
        "Check the voltage printed on the supply and on the servos."
    )


def briefing(role: ArmRole) -> str:
    """Everything to read before the first motor is connected."""
    lines = [
        f"Motor setup for the {role.value} arm.",
        "",
        "Wiring order, gripper first. Connect the controller board to ONE motor",
        "at a time; LeRobot asks before each one:",
    ]
    ratios = GEAR_RATIOS[role]
    for motor_id in range(len(JOINT_NAMES), 0, -1):
        name = JOINT_NAMES[motor_id - 1]
        lines.append(f"  motor id {motor_id}: {name}")
    lines += ["", f"Gear ratio per joint ({role.value}):"]
    for motor_id, name in enumerate(JOINT_NAMES, start=1):
        lines.append(f"  {motor_id} {name}: 1/{ratios[motor_id - 1]}")
    lines += ["", power_warning(role), ""]
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="so101-setup-motors",
        description="Set the motor IDs of one SO-101 arm with LeRobot.",
    )
    parser.add_argument("--role", required=True, choices=[r.value for r in ArmRole])
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the checklist and the command; ask and run nothing",
    )
    parser.add_argument(
        "--config", type=Path, help="machine config (default: configs/local.yaml)"
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    runner: Runner = _run,
    input_fn: InputFn = input,
    root: Path | None = None,
) -> int:
    args = _parser().parse_args(argv)
    role = ArmRole(args.role)
    try:
        workspace = root if root is not None else find_workspace_root()
        config = load_local_config(workspace, args.config)
        command = setup_motors_argv(config, role, workspace)
    except (WorkspaceError, ValueError) as err:
        print(f"so101-setup-motors: {err}", file=sys.stderr)
        return 1

    print(briefing(role))
    print(f"Command: {format_command(command)}")
    if args.dry_run:
        print("\nDry run: nothing was asked or run.")
        return 0

    try:
        reply = input_fn("\nType 'y' to run it: ")
    except EOFError:
        reply = ""
    if reply.strip().lower() not in {"y", "yes"}:
        print("Aborted.")
        return 1
    return runner(command)


def cli() -> None:
    sys.exit(main())
