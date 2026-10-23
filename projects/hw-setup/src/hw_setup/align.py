"""Check that the leader and follower are in the same pose before teleop.

``so101-teleop`` and ``so101-record`` call ``alignment_gate`` before they
build the LeRobot command; ``so101-align`` prints the table (``--watch``
refreshes it about twice a second) and writes
``outputs/hw/alignment-<UTC time>.json``.

What LeRobot 0.6.1 does, and why this check does not call ``connect()``
(paths relative to ``site-packages/lerobot``):

- ``SOFollower.connect(calibrate=False)`` still calls ``configure()``
  (robots/so_follower/so_follower.py L91-109), which writes PID gains and
  limits inside ``bus.torque_disabled()``; that context manager re-enables
  torque when it exits (motors/motors_bus.py L677-691). ``SOLeader.connect``
  also calls ``configure()``, which disables torque and writes registers
  (teleoperators/so_leader/so_leader.py L68-78, L127-131). With
  ``calibrate=True`` either may ask ENTER/c and write the file to the motors
  when ``is_calibrated`` is False (so_follower.py L99-124). So neither
  ``connect`` is used.
- Instead the robot and teleoperator objects are built from the very argv
  the wrappers run (``teleoperate_argv``, parsed with LeRobot's own
  ``TeleoperateConfig``), which loads ``<calibration_dir>/<id>.json`` into
  ``device.bus.calibration`` (robots/robot.py L46-56). Only their buses are
  used: ``bus.connect()`` opens the port and pings each motor and reads its
  firmware (motors/motors_bus.py L514-540, motors/feetech/feetech.py
  L155-157); ``bus.is_calibrated`` reads the Homing_Offset and position
  limit registers and compares them with the file (feetech.py L228-266);
  ``bus.sync_read("Present_Position")`` reads and normalises positions
  (motors_bus.py L1128-1171). All of these only read. No goal is written
  and torque is never touched.
- ``bus.disconnect(disable_torque=False)`` only closes the port; with True
  it would write Torque_Enable=0 and Lock=0 to every motor first
  (motors_bus.py L547-562). It runs in a ``finally`` for every bus whose
  port is open, also when a later connect or read fails. The robot's own
  ``__del__`` disconnects with torque disable when the bus is still open
  (robots/robot.py L76-85); closing every port here keeps it from acting.

Units are the ones teleop uses, because the same LeRobot normalisation runs:
degrees for the five body joints (``use_degrees`` defaults to True,
config_so_follower.py L42; ``(raw - mid) * 360 / 4095``, motors_bus.py
L874-877) and percent of the calibrated range for the gripper
(``RANGE_0_100``, L871-873). ``--align-max`` is in the same units.

The difference is ``leader - follower`` and is not wrapped at +-180 degrees,
wrist_roll included. wrist_roll is calibrated over the full raw range
(range_min 0, range_max 4095), but the follower is a position servo: the
leader's value is turned back into an absolute raw goal in 0-4095
(motors_bus.py L904-907) and the servo moves along that range, never across
the 0/4095 seam. A leader at +179 and a follower at -179 degrees make the
follower turn 358 degrees, so 358 is the honest difference; wrapping would
call it 2 and let the jump through. LeRobot's ``max_relative_target`` clamp
uses the same unwrapped difference (robots/utils.py L107-112).

When the motors hold a different calibration from the file, the reading is
not what teleop will see: ``lerobot-teleoperate`` connects with
``calibrate=True``, asks, and on ENTER writes the file's homing offsets to
the motors, which shifts every position. That arm is reported and the check
fails.
"""

import argparse
import json
import math
import sys
import time
from collections.abc import Callable, Sequence
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hw_setup.lerobot_argv import teleoperate_argv
from hw_setup.workspace import WorkspaceError, find_workspace_root, load_local_config
from so101.arm import ArmRole
from so101.machine_config import MachineConfig

PROG = "so101-align"
JOINTS = (
    "shoulder_pan",
    "shoulder_lift",
    "elbow_flex",
    "wrist_flex",
    "wrist_roll",
    "gripper",
)
DEFAULT_ALIGN_MAX = 5.0
WATCH_PERIOD_S = 0.5
NUM_READ_RETRIES = 2  # LeRobot's own default, config_so_follower.py L53
OUTPUT_DIR = Path("outputs") / "hw"
FIX = (
    "To fix: pose the arms the same, leader matching follower (so101-align "
    "--watch shows the gap live), or, if the same pose reads differently, "
    "recalibrate with so101-calibrate --role <leader|follower>."
)
SKIP_WARNING = (
    "WARNING: --skip-align: the arms were not checked. If the leader and the "
    "follower are not in the same pose, the follower will move to the leader's "
    "pose as soon as teleop starts."
)
# What a read can raise: no port (ConnectionError, an OSError), a missing
# motor or bad packet (RuntimeError), or an invalid calibration (ValueError).
READ_ERRORS = (OSError, RuntimeError, ValueError)
_UNITS = {"degrees": "deg", "range_0_100": "%", "range_m100_100": "%"}

# A device is a LeRobot robot or teleoperator; only ``device.bus`` is used.
DeviceFactory = Callable[[MachineConfig, Path], dict[ArmRole, Any]]


@dataclass(frozen=True)
class JointGap:
    joint: str
    leader: float
    follower: float
    unit: str  # "deg" or "%"

    @property
    def diff(self) -> float:
        """``leader - follower``: where the follower would move. Not wrapped."""
        return self.leader - self.follower


@dataclass(frozen=True)
class Alignment:
    joints: tuple[JointGap, ...]
    motors_match_file: dict[ArmRole, bool]

    def over(self, limit: float) -> list[JointGap]:
        return [j for j in self.joints if abs(j.diff) > limit]

    def ok(self, limit: float) -> bool:
        return not self.over(limit) and all(self.motors_match_file.values())


def make_devices(config: MachineConfig, root: Path) -> dict[ArmRole, Any]:
    """The LeRobot follower and leader, built as ``so101-teleop`` builds them.

    The argv is the one the wrapper runs (without cameras, which are not
    needed), parsed with LeRobot's ``TeleoperateConfig``. Building opens no
    port. Imported late: LeRobot is slow to import.
    """
    import draccus
    from lerobot.robots.utils import make_robot_from_config
    from lerobot.scripts.lerobot_teleoperate import TeleoperateConfig
    from lerobot.teleoperators.utils import make_teleoperator_from_config

    argv = teleoperate_argv(config, root, max_relative_target=None, cameras=False)
    cfg = draccus.parse(config_class=TeleoperateConfig, args=argv[1:])
    return {
        ArmRole.FOLLOWER: make_robot_from_config(cfg.robot),
        ArmRole.LEADER: make_teleoperator_from_config(cfg.teleop),
    }


def _close(bus: Any) -> None:
    """Close the port without touching torque (no write to the motors)."""
    if bus.is_connected:
        bus.disconnect(disable_torque=False)


def _unit(bus: Any, joint: str) -> str:
    mode = bus.motors[joint].norm_mode
    return _UNITS.get(getattr(mode, "value", str(mode)), str(mode))


class ArmReader:
    """Both buses open, read-only. Use as a context manager.

    ``__enter__`` connects each bus and reads ``is_calibrated``; ``read``
    takes one sync read of ``Present_Position`` per arm. ``__exit__`` closes
    every open port with ``disable_torque=False``, also on error.
    """

    def __init__(self, devices: dict[ArmRole, Any]) -> None:
        self._buses = {role: devices[role].bus for role in ArmRole}
        self._stack = ExitStack()
        self.motors_match_file: dict[ArmRole, bool] = {}

    def __enter__(self) -> "ArmReader":
        try:
            for role, bus in self._buses.items():
                self._stack.callback(_close, bus)  # before connect: it may fail
                bus.connect(handshake=True)
                self.motors_match_file[role] = bool(bus.is_calibrated)
        except BaseException:
            self._stack.close()
            raise
        return self

    def __exit__(self, *exc: object) -> None:
        self._stack.close()

    def read(self) -> Alignment:
        positions = {
            role: bus.sync_read("Present_Position", num_retry=NUM_READ_RETRIES)
            for role, bus in self._buses.items()
        }
        follower_bus = self._buses[ArmRole.FOLLOWER]
        joints = tuple(
            JointGap(
                joint,
                leader=float(positions[ArmRole.LEADER][joint]),
                follower=float(positions[ArmRole.FOLLOWER][joint]),
                unit=_unit(follower_bus, joint),
            )
            for joint in JOINTS
        )
        return Alignment(joints, dict(self.motors_match_file))


def check_alignment(
    config: MachineConfig, root: Path, *, device_factory: DeviceFactory | None = None
) -> Alignment:
    """Connect both arms read-only, read once, disconnect."""
    factory = device_factory if device_factory is not None else make_devices
    with ArmReader(factory(config, root)) as reader:
        return reader.read()


def _fmt(value: float, unit: str, sign: bool = False) -> str:
    symbol = "°" if unit == "deg" else "%"
    return f"{value:+.1f}{symbol}" if sign else f"{value:.1f}{symbol}"


def format_table(alignment: Alignment, limit: float) -> str:
    lines = [
        f"{'joint':<14}{'leader':>10}{'follower':>10}{'diff':>10}{'limit':>8}  status"
    ]
    for j in alignment.joints:
        status = "OVER" if abs(j.diff) > limit else "ok"
        lines.append(
            f"{j.joint:<14}{_fmt(j.leader, j.unit):>10}{_fmt(j.follower, j.unit):>10}"
            f"{_fmt(j.diff, j.unit, sign=True):>10}{_fmt(limit, j.unit):>8}  {status}"
        )
    for role, match in alignment.motors_match_file.items():
        if not match:
            lines.append(
                f"{role.value}: the motors hold a different calibration from "
                f"hardware/calibration/{role.value}/<id>.json; LeRobot would write "
                "the file to the motors at connect, which moves every reading. "
                f"Recalibrate with so101-calibrate --role {role.value}."
            )
    return "\n".join(lines)


def record(alignment: Alignment, limit: float, now: datetime) -> dict[str, Any]:
    return {
        "time_utc": now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "limit": limit,
        "aligned": alignment.ok(limit),
        "joints": {
            j.joint: {
                "leader": j.leader,
                "follower": j.follower,
                "diff": j.diff,
                "unit": j.unit,
                "over": abs(j.diff) > limit,
            }
            for j in alignment.joints
        },
        "motors_match_file": {
            role.value: match for role, match in alignment.motors_match_file.items()
        },
    }


def write_record(
    root: Path, alignment: Alignment, limit: float, *, now: datetime
) -> Path:
    """Write ``outputs/hw/alignment-<UTC time>.json`` (gitignored)."""
    stamp = now.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = root / OUTPUT_DIR / f"alignment-{stamp}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record(alignment, limit, now), indent=2) + "\n")
    return path


def align_max(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a number: {text!r}") from None
    if not (math.isfinite(value) and value > 0):
        raise argparse.ArgumentTypeError(f"must be more than 0, got {text!r}")
    return value


def _add_align_max(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--align-max",
        type=align_max,
        default=DEFAULT_ALIGN_MAX,
        help="largest leader-follower gap allowed: degrees for the body joints, "
        f"%% of range for the gripper (default: {DEFAULT_ALIGN_MAX})",
    )


def add_align_arguments(parser: argparse.ArgumentParser) -> None:
    """``--align-max`` and ``--skip-align`` for so101-teleop and so101-record."""
    _add_align_max(parser)
    parser.add_argument(
        "--skip-align",
        action="store_true",
        help="do not check that the arms are in the same pose (warns)",
    )


def alignment_gate(
    config: MachineConfig,
    root: Path,
    *,
    limit: float,
    skip: bool,
    dry_run: bool,
    prog: str,
    device_factory: DeviceFactory | None = None,
) -> int | None:
    """Run the check for a wrapper: None to go on, or the exit code (1)."""
    if skip:
        print(f"{prog}: {SKIP_WARNING}", file=sys.stderr)
        return None
    if dry_run:
        print(
            "Alignment check: would run (connect both arms read-only, refuse if "
            f"any joint differs by more than {limit}); not run under --dry-run."
        )
        return None
    try:
        alignment = check_alignment(config, root, device_factory=device_factory)
    except READ_ERRORS as err:
        print(
            f"{prog}: refusing to run: could not read the arms: {err}", file=sys.stderr
        )
        return 1
    if not alignment.ok(limit):
        names = ", ".join(j.joint for j in alignment.over(limit)) or "calibration"
        print(
            f"{prog}: refusing to run: leader and follower disagree ({names}).\n"
            f"{format_table(alignment, limit)}\n{FIX}",
            file=sys.stderr,
        )
        return 1
    print(format_table(alignment, limit))
    print(f"Alignment checked: every joint within {limit}.")
    return None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Show how far the leader and follower poses differ, per "
        "joint. Read-only: sends no goal and does not change torque.",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help=f"refresh every {WATCH_PERIOD_S} s until Ctrl-C",
    )
    _add_align_max(parser)
    parser.add_argument(
        "--config", type=Path, help="machine config (default: configs/local.yaml)"
    )
    return parser


def _show(alignment: Alignment, limit: float, clear: bool) -> None:
    if clear:
        print("\033[H\033[2J", end="")
    print(format_table(alignment, limit), flush=True)


def main(
    argv: Sequence[str] | None = None,
    *,
    root: Path | None = None,
    device_factory: DeviceFactory | None = None,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> int:
    """Exit 0 when the last reading is within ``--align-max``, else 1."""
    args = _parser().parse_args(argv)
    try:
        workspace = root if root is not None else find_workspace_root()
        config = load_local_config(workspace, args.config)
        factory = device_factory if device_factory is not None else make_devices
        devices = factory(config, workspace)
    except (WorkspaceError, ValueError) as err:
        print(f"{PROG}: {err}", file=sys.stderr)
        return 1

    clear = args.watch and sys.stdout.isatty()
    latest: Alignment | None = None
    try:
        with ArmReader(devices) as reader:
            while True:
                latest = reader.read()
                _show(latest, args.align_max, clear)
                if not args.watch:
                    break
                sleep(WATCH_PERIOD_S)
    except KeyboardInterrupt:
        print()
    except READ_ERRORS as err:
        print(f"{PROG}: could not read the arms: {err}", file=sys.stderr)
        return 1
    if latest is None:
        return 1
    path = write_record(workspace, latest, args.align_max, now=now())
    try:
        shown = path.relative_to(workspace)
    except ValueError:
        shown = path
    print(f"Saved: {shown}")
    if latest.ok(args.align_max):
        print(f"Aligned: every joint within {args.align_max}.")
        return 0
    print(FIX)
    return 1


def cli() -> None:
    sys.exit(main())
