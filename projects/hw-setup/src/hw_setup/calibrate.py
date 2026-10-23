"""``so101-calibrate``: run ``lerobot-calibrate`` for one arm, then check it.

Before the run the current file is copied to a timestamped backup. After the
run the new file is loaded, sanity-checked (``so101.check_calibration``) and
compared with the old one joint by joint (``so101.format_diff``).

What LeRobot 0.6.1 does (paths relative to ``site-packages/lerobot``):

- It reads and writes exactly ``<calibration_dir>/<id>.json`` and loads that
  file when the arm object is built (robots/robot.py L49-56,
  teleoperators/teleoperator.py L47-56). Nothing else in the folder is read.
- ``lerobot-calibrate`` connects without calibrating, then calls
  ``calibrate()`` (scripts/lerobot_calibrate.py L96-99).
- When the file exists, ``calibrate()`` asks: any reply but ``c`` writes
  the existing file to the motors and returns, leaving the file as it was;
  ``c`` then ENTER runs a new calibration (robots/so_follower/so_follower.py L116-124,
  teleoperators/so_leader/so_leader.py L85-92). With no file it goes straight
  to calibration.
- A new calibration is written to the motors first, then saved to the file
  (so_follower.py L155-156), so after a run the motors hold the new values.

Backups go to ``<calibration_dir>/backups/<id>.<UTC time>.json.bak``: LeRobot
never reads it, and the ``.bak`` suffix keeps it out of the CI check that
loads every ``*.json`` under ``hardware/calibration/``. The folder is
gitignored; committed calibrations already have their history in git.

An existing file that cannot be loaded is refused before LeRobot runs:
LeRobot loads it when the arm object is built (robots/robot.py L56) and
crashes before it asks anything, so every retry would only add a backup.
``--move-corrupt`` moves it to the backup path and calibrates from scratch.

A file that fails the check is not restored automatically: the motors already
hold the new values, and the checks are heuristics the owner may overrule.
"""

import argparse
import os
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

from hw_setup.lerobot_argv import calibrate_argv, calibration_dir, format_command
from hw_setup.workspace import WorkspaceError, find_workspace_root, load_local_config
from so101.arm import ArmRole
from so101.calibration import (
    CalibrationError,
    JointCalibration,
    check_calibration,
    load_calibration,
)
from so101.calibration_diff import diff_calibrations, format_diff

Runner = Callable[[list[str]], int]
Clock = Callable[[], datetime]

BACKUP_DIR = "backups"
PROG = "so101-calibrate"


def _run(argv: list[str]) -> int:
    return subprocess.run(argv, check=False).returncode


def _utc_now() -> datetime:
    return datetime.now(UTC)


def backup_path(target: Path, now: datetime) -> Path:
    """Where ``target`` is copied before a run: never a ``*.json`` LeRobot loads."""
    stamp = now.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    return target.parent / BACKUP_DIR / f"{target.stem}.{stamp}.json.bak"


def _err(message: str) -> None:
    print(message, file=sys.stderr)


def _load(path: Path) -> tuple[dict[str, JointCalibration] | None, str]:
    """The calibration at ``path``, or None and the reason it cannot load."""
    try:
        return load_calibration(path), ""
    except (CalibrationError, ValueError, OSError) as err:
        return None, str(err)


def lerobot_can_load(path: Path) -> bool:
    """Whether LeRobot's own loader reads ``path`` (robots/robot.py L159-160).

    It only needs JSON objects with the five integer motor keys; so101's
    checks (all six joints, range order) are stricter.
    """
    import draccus
    from lerobot.motors.motors_bus import MotorCalibration

    # draccus annotates ``load`` for dataclasses only, but LeRobot passes this
    # exact dict type (robots/robot.py L160) and it works at runtime.
    calibration_type = dict[str, MotorCalibration]
    try:
        with path.open() as f, draccus.config_type("json"):
            draccus.load(calibration_type, f)  # ty: ignore[invalid-argument-type]
    except Exception:  # draccus raises several unrelated types on bad input
        return False
    return True


def copy_new(src: Path, dst: Path) -> None:
    """Copy ``src`` to ``dst``; FileExistsError if ``dst`` exists."""
    with src.open("rb") as fin:
        fout = dst.open("xb")  # FileExistsError here leaves nothing to remove
        try:
            with fout:  # closing flushes, so a close error is cleaned up too
                shutil.copyfileobj(fin, fout)
        except BaseException:
            dst.unlink(missing_ok=True)
            raise
    shutil.copystat(src, dst)


def move_new(src: Path, dst: Path) -> None:
    """Move ``src`` to ``dst``; FileExistsError if ``dst`` exists."""
    os.link(src, dst)
    src.unlink()


def _label(crash: bool) -> str:
    return "unreadable" if crash else "invalid"


def _refuse_corrupt(target: Path, backup: Path, reason: str, crash: bool) -> int:
    _err(f"{PROG}: the existing calibration file is {_label(crash)}: {reason}")
    if target.is_dir():
        # robots/robot.py L55 checks is_file(), so LeRobot skips a directory.
        _err("LeRobot would calibrate, write the motors, then fail to save.")
    elif crash:
        _err("LeRobot would crash loading it before it asks anything.")
    else:
        _err("It fails the sanity checks, so it is no base to recalibrate from.")
    _err("Move it aside, then run again:")
    _err(f"  {shlex.join(['mkdir', '-p', str(backup.parent)])}")
    _err(f"  {shlex.join(['mv', str(target), str(backup)])}")
    _err("or rerun with --move-corrupt to do that and calibrate.")
    return 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description=(
            "Calibrate one SO-101 arm with LeRobot, back up the old file, "
            "check the new one and print what changed per joint."
        ),
    )
    parser.epilog = (
        "At LeRobot's prompt, 'c' then ENTER recalibrates; anything other than "
        "'c' writes the stored calibration file to the motors and leaves the "
        "file as it was (so_follower.py L116-124)."
    )
    parser.add_argument("--role", required=True, choices=[r.value for r in ArmRole])
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the plan and the command; back up, run and write nothing",
    )
    parser.add_argument(
        "--move-corrupt",
        action="store_true",
        help="move an unreadable existing file to the backup path, then calibrate",
    )
    parser.add_argument(
        "--config", type=Path, help="machine config (default: configs/local.yaml)"
    )
    return parser


def _print_plan(target: Path, backup: Path | None, command: list[str]) -> None:
    print(f"Calibration file: {target}")
    print(f"Backup: {backup if backup else 'none, first calibration'}")
    print(f"Command: {format_command(command)}")
    if backup:
        print(
            "LeRobot will find the existing file and ask what to do: type 'c' "
            "and press ENTER to recalibrate; anything other than 'c' writes the "
            "stored calibration file to the motors."
        )
    else:
        print("No calibration file yet: LeRobot goes straight to calibration.")


def _backup_hint(target: Path, backup: Path | None) -> bool:
    """Print where the backup is and how to restore it; False if there is none."""
    if backup is None:
        _err("There is no previous file to restore.")
        return False
    _err(f"The previous calibration is backed up at {backup}")
    _err(f"To restore it: {shlex.join(['cp', str(backup), str(target)])}")
    return True


def _restore_hint(target: Path, backup: Path | None) -> None:
    if not _backup_hint(target, backup):
        _err(f"Run {PROG} again to recalibrate.")
        return
    _err(
        "The motors now hold the new values; after a restore, LeRobot sees the "
        "file and motors differ on the next connect and asks to write the file "
        "to the motors (press ENTER)."
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    runner: Runner = _run,
    root: Path | None = None,
    now: Clock = _utc_now,
) -> int:
    args = _parser().parse_args(argv)
    role = ArmRole(args.role)
    try:
        workspace = root if root is not None else find_workspace_root()
        config = load_local_config(workspace, args.config)
        command = calibrate_argv(config, role, workspace)
        target = calibration_dir(workspace, role) / f"{config.arms[role].arm_id}.json"
    except (WorkspaceError, ValueError) as err:
        _err(f"{PROG}: {err}")
        return 1

    backup = backup_path(target, now()) if target.exists() else None
    old, reason = _load(target) if backup is not None else (None, "")
    corrupt = backup is not None and old is None
    crash = corrupt and not lerobot_can_load(target)
    if backup is not None and corrupt and not args.move_corrupt:
        return _refuse_corrupt(target, backup, reason, crash)
    if backup is not None and backup.exists():
        _err(f"{PROG}: backup {backup} already exists; not overwriting it")
        return 1

    if corrupt:
        print(f"Calibration file: {target} ({_label(crash)}: {reason})")
        verb = "would move" if args.dry_run else "moving"
        print(f"Backup: {verb} the {_label(crash)} file to {backup}")
        print(f"Command: {format_command(command)}")
        print("LeRobot then finds no file and goes straight to calibration.")
    else:
        _print_plan(target, backup, command)
    if args.dry_run:
        print("Dry run: nothing was backed up, moved, run or written.")
        return 0

    if backup is not None:
        try:
            backup.parent.mkdir(exist_ok=True)
            if corrupt:
                move_new(target, backup)
            else:
                copy_new(target, backup)
        except FileExistsError:
            _err(f"{PROG}: backup {backup} already exists; not overwriting it")
            return 1
        except OSError as err:
            action = "move" if corrupt else "back up"
            _err(f"{PROG}: cannot {action} {target} to {backup}: {err}")
            return 1
        if corrupt:
            print(f"Moved the {_label(crash)} {target} to {backup}")
        else:
            print(f"Backed up {target} to {backup}")

    # A moved-aside unreadable file is not worth restoring.
    restorable = None if corrupt else backup
    try:
        code = runner(command)
    except KeyboardInterrupt:
        _err(f"\n{PROG}: interrupted while lerobot-calibrate was running")
        _backup_hint(target, restorable)
        return 130
    if code != 0:
        _err(f"{PROG}: lerobot-calibrate exited with code {code}")
        _backup_hint(target, restorable)
        return code
    if not target.is_file():
        _err(f"{PROG}: no calibration file at {target} after lerobot-calibrate")
        return 1

    if backup is not None and target.read_bytes() == backup.read_bytes():
        backup.unlink()
        print(
            "Calibration file unchanged: the existing file was kept (no 'c' at "
            "LeRobot's prompt), so the identical backup was removed. To "
            "recalibrate, run again and type 'c'."
        )
        return 0

    try:
        new = load_calibration(target)
        if old is not None:
            print("Changes per joint:")
            print(format_diff(diff_calibrations(old, new)))
        elif corrupt:
            print("The previous file was unreadable, so there is no diff.")
        else:
            print("First calibration: no previous file, so no backup and no diff.")
        check_calibration(new)
    except (CalibrationError, ValueError) as err:
        _err(f"{PROG}: {target} failed the sanity checks: {err}")
        _restore_hint(target, restorable)
        return 1

    print(f"Sanity checks passed: {target}")
    if backup is not None:
        print(f"Previous file: {backup}")
    return 0


def cli() -> None:
    sys.exit(main())
