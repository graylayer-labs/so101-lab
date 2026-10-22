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
