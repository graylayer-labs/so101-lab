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
    ["valid", "range_order_pass", "range_width_pass", "gripper_span_pass", "ids_pass"],
)
def test_passing_fixtures_have_no_errors(fixture: str):
    check_calibration(_fixture(fixture))


@pytest.mark.parametrize(
    ("fixture", "joint", "check"),
    [
        ("range_order_fail", "elbow_flex", "range_order"),
        ("range_width_fail", "wrist_flex", "range_width"),
        ("gripper_span_fail", "gripper", "gripper_span"),
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
