import json
from pathlib import Path

import pytest

from so101.arm import JOINT_NAMES, ArmRole
from so101.calibration import (
    CalibrationError,
    JointCalibration,
    calibration_path,
    load_calibration,
)


def _valid_payload() -> dict[str, dict[str, int]]:
    return {
        name: {
            "id": motor_id,
            "drive_mode": 0,
            "homing_offset": -12 * motor_id,
            "range_min": 800,
            "range_max": 3200,
        }
        for motor_id, name in enumerate(JOINT_NAMES, start=1)
    }


def _write(tmp_path: Path, payload: object) -> Path:
    path = tmp_path / "arm.json"
    path.write_text(json.dumps(payload))
    return path


def test_calibration_path_follows_role_and_arm_id(tmp_path: Path):
    path = calibration_path(tmp_path, ArmRole.FOLLOWER, "main")
    assert path == tmp_path / "follower" / "main.json"


def test_load_calibration_reads_every_joint(tmp_path: Path):
    calib = load_calibration(_write(tmp_path, _valid_payload()))
    assert tuple(calib) == JOINT_NAMES
    assert calib["gripper"] == JointCalibration(
        id=6, drive_mode=0, homing_offset=-72, range_min=800, range_max=3200
    )


def test_load_calibration_rejects_missing_joint(tmp_path: Path):
    payload = _valid_payload()
    del payload["wrist_roll"]
    with pytest.raises(CalibrationError, match="wrist_roll"):
        load_calibration(_write(tmp_path, payload))


def test_load_calibration_rejects_unknown_joint(tmp_path: Path):
    payload = _valid_payload()
    payload["elbow"] = payload["elbow_flex"]
    with pytest.raises(CalibrationError, match="elbow"):
        load_calibration(_write(tmp_path, payload))


def test_load_calibration_rejects_inverted_range(tmp_path: Path):
    payload = _valid_payload()
    payload["elbow_flex"]["range_min"] = 3500
    with pytest.raises(CalibrationError, match="elbow_flex"):
        load_calibration(_write(tmp_path, payload))


def test_load_calibration_rejects_range_outside_encoder(tmp_path: Path):
    payload = _valid_payload()
    payload["gripper"]["range_max"] = 4096
    with pytest.raises(CalibrationError, match="gripper"):
        load_calibration(_write(tmp_path, payload))


def test_load_calibration_rejects_missing_field(tmp_path: Path):
    payload = _valid_payload()
    del payload["shoulder_pan"]["homing_offset"]
    with pytest.raises(CalibrationError, match="homing_offset"):
        load_calibration(_write(tmp_path, payload))


def test_load_calibration_rejects_missing_file(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_calibration(tmp_path / "nope.json")
