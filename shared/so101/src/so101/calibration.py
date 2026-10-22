"""Load and check per-arm calibration files.

Files live at ``hardware/calibration/<role>/<arm_id>.json`` and use the layout
LeRobot writes for the SO-101.
"""

import json
from dataclasses import dataclass, fields
from pathlib import Path

from so101.arm import JOINT_NAMES, ArmRole

# STS3215 servos report position as a 12-bit encoder count.
ENCODER_MAX = 4095
# A joint calibrated over fewer counts than this (about 17 degrees) was
# almost certainly not moved through its range.
MIN_RANGE_WIDTH = 200
# The gripper opens over a limited span; outside it the file is suspect.
GRIPPER_SPAN = (300, 2500)


class CalibrationError(ValueError):
    """A calibration file is missing joints or holds impossible values."""


@dataclass(frozen=True)
class JointCalibration:
    id: int
    drive_mode: int
    homing_offset: int
    range_min: int
    range_max: int


def calibration_path(root: Path, role: ArmRole, arm_id: str) -> Path:
    """Where the calibration file for one arm lives under ``root``."""
    return root / role.value / f"{arm_id}.json"


def load_calibration(path: Path) -> dict[str, JointCalibration]:
    """Read a calibration file and return its joints in JOINT_NAMES order."""
    raw = json.loads(path.read_text())
    if not isinstance(raw, dict):
        raise CalibrationError(f"{path}: expected a JSON object of joints")

    missing = [name for name in JOINT_NAMES if name not in raw]
    unknown = [name for name in raw if name not in JOINT_NAMES]
    if missing:
        raise CalibrationError(f"{path}: missing joint(s): {', '.join(missing)}")
    if unknown:
        raise CalibrationError(f"{path}: unknown joint(s): {', '.join(unknown)}")

    return {name: _parse_joint(path, name, raw[name]) for name in JOINT_NAMES}


def _parse_joint(path: Path, name: str, entry: object) -> JointCalibration:
    if not isinstance(entry, dict):
        raise CalibrationError(f"{path}: joint {name} must be a JSON object")
    values: dict[str, int] = {}
    for f in fields(JointCalibration):
        value = entry.get(f.name)
        if not isinstance(value, int) or isinstance(value, bool):
            raise CalibrationError(f"{path}: joint {name} needs integer {f.name}")
        values[f.name] = value
    joint = JointCalibration(**values)
    if not 0 <= joint.range_min < joint.range_max <= ENCODER_MAX:
        raise CalibrationError(
            f"{path}: joint {name} range must satisfy "
            f"0 <= range_min < range_max <= {ENCODER_MAX}"
        )
    return joint


def check_calibration(calib: dict[str, JointCalibration]) -> None:
    """Sanity-check a calibration; raise one CalibrationError listing every failure.

    Each message names the joint and the check: ``range_order``,
    ``range_width``, ``gripper_span`` or ``joint_id``.
    """
    problems: list[str] = []
    for motor_id, name in enumerate(JOINT_NAMES, start=1):
        joint = calib.get(name)
        if joint is None:
            problems.append(f"joint {name} failed check joint_id: missing")
            continue
        if joint.id != motor_id:
            problems.append(
                f"joint {name} failed check joint_id: id is {joint.id}, "
                f"expected {motor_id}"
            )
        width = joint.range_max - joint.range_min
        if joint.range_min >= joint.range_max:
            problems.append(
                f"joint {name} failed check range_order: range_min "
                f"{joint.range_min} is not below range_max {joint.range_max}"
            )
            continue
        if width < MIN_RANGE_WIDTH:
            problems.append(
                f"joint {name} failed check range_width: width {width} is "
                f"below {MIN_RANGE_WIDTH}"
            )
        low, high = GRIPPER_SPAN
        if name == "gripper" and not low <= width <= high:
            problems.append(
                f"joint {name} failed check gripper_span: span {width} is "
                f"outside {low} to {high}"
            )
    if problems:
        raise CalibrationError("; ".join(problems))
