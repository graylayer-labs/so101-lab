import json
from pathlib import Path

import pytest

from so101.arm import JOINT_NAMES
from so101.calibration import (
    CalibrationError,
    JointCalibration,
    check_calibration,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(name: str) -> dict[str, JointCalibration]:
    # Built directly, not through load_calibration, so that fixtures with bad
    # values reach the checks instead of being rejected by the loader.
    raw = json.loads((FIXTURES / f"{name}.json").read_text())
    return {n: JointCalibration(**raw[n]) for n in JOINT_NAMES}


@pytest.mark.parametrize(
    "fixture",
    [
        "valid",
        "range_order_pass",
        "range_width_pass",  # wrist_flex width exactly 200
        "gripper_span_pass",  # gripper width exactly 300
        "gripper_span_pass_high",  # gripper width exactly 2500
        "ids_pass",
    ],
)
def test_passing_fixtures_have_no_errors(fixture: str):
    check_calibration(_fixture(fixture))


@pytest.mark.parametrize(
    ("fixture", "joint", "check"),
    [
        ("range_order_fail", "elbow_flex", "range_order"),
        ("range_width_fail", "wrist_flex", "range_width"),
        ("gripper_span_fail", "gripper", "gripper_span"),
        ("gripper_span_fail_high", "gripper", "gripper_span"),
        ("ids_fail", "shoulder_lift", "joint_id"),
    ],
)
def test_failing_fixtures_name_joint_and_check(fixture: str, joint: str, check: str):
    with pytest.raises(CalibrationError) as exc:
        check_calibration(_fixture(fixture))
    message = str(exc.value)
    assert joint in message
    assert check in message


def test_all_failures_are_reported_together():
    calib = _fixture("ids_fail")
    calib["wrist_flex"] = JointCalibration(4, 0, 0, 2000, 2050)
    with pytest.raises(CalibrationError) as exc:
        check_calibration(calib)
    assert "shoulder_lift" in str(exc.value)
    assert "wrist_flex" in str(exc.value)


@pytest.mark.parametrize(
    ("fixture", "check"),
    [
        ("gripper_span_fail", "gripper_span"),  # width 250, below 300
        ("gripper_span_fail_high", "gripper_span"),  # width 3000, above 2500
    ],
)
def test_gripper_fixtures_trip_only_the_span_check(fixture: str, check: str):
    with pytest.raises(CalibrationError) as exc:
        check_calibration(_fixture(fixture))
    message = str(exc.value)
    assert check in message
    assert "range_width" not in message
    assert "range_order" not in message
    assert "joint_id" not in message


def test_missing_joint_is_reported_without_stopping_other_checks():
    calib = _fixture("valid")
    del calib["wrist_flex"]
    calib["elbow_flex"] = JointCalibration(3, 0, 0, 1000, 1100)
    with pytest.raises(CalibrationError) as exc:
        check_calibration(calib)
    message = str(exc.value)
    assert "joint wrist_flex failed check joint_id: missing" in message
    assert "elbow_flex" in message
    assert "range_width" in message


def test_range_order_check_catches_inverted_range():
    # load_calibration already rejects range_min >= range_max, so this check
    # is only reachable through a dict built by hand.
    calib = _fixture("valid")
    calib["elbow_flex"] = JointCalibration(3, 0, 0, 2000, 2000)
    with pytest.raises(CalibrationError, match="elbow_flex failed check range_order"):
        check_calibration(calib)
