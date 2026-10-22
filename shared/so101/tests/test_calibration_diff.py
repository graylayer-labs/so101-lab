from dataclasses import replace
from pathlib import Path

from so101.calibration import load_calibration
from so101.calibration_diff import diff_calibrations, format_diff

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str):
    return load_calibration(FIXTURES / f"{name}.json")


def test_identical_calibrations_have_no_changes():
    calib = _load("follower_main")
    diff = diff_calibrations(calib, calib)
    assert not diff.has_changes
    assert diff.added == () and diff.removed == ()
    assert "no differences" in format_diff(diff)


def test_changed_fields_report_old_new_and_delta():
    old, new = _load("follower_main"), _load("follower_recalibrated")
    diff = diff_calibrations(old, new)
    changes = {(c.joint, c.field): c for c in diff.changes}
    assert set(changes) == {
        ("elbow_flex", "homing_offset"),
        ("wrist_roll", "range_max"),
        ("gripper", "drive_mode"),
    }
    c = changes[("elbow_flex", "homing_offset")]
    assert (c.old, c.new, c.delta) == (1207, 1247, 40)
    c = changes[("wrist_roll", "range_max")]
    assert c.delta == -100
    assert changes[("gripper", "drive_mode")].delta is None


def test_added_and_removed_joints():
    old = _load("follower_main")
    new = dict(old)
    removed = new.pop("gripper")
    new["extra"] = replace(removed, id=7)
    diff = diff_calibrations(old, new)
    assert diff.removed == ("gripper",)
    assert diff.added == ("extra",)
    assert diff.changes == ()
    assert diff.has_changes


def test_format_is_a_table_listing_changes():
    diff = diff_calibrations(_load("follower_main"), _load("follower_recalibrated"))
    text = format_diff(diff)
    lines = text.splitlines()
    assert lines[0].split() == ["joint", "field", "old", "new", "delta"]
    row = next(line for line in lines if "elbow_flex" in line)
    assert row.split() == ["elbow_flex", "homing_offset", "1207", "1247", "+40"]
    assert any("wrist_roll" in line and "-100" in line for line in lines)
    grip = next(line for line in lines if "gripper" in line)
    assert grip.split() == ["gripper", "drive_mode", "0", "1", "-"]


def test_format_lists_added_and_removed_joints():
    old = _load("follower_main")
    new = dict(old)
    del new["gripper"]
    text = format_diff(diff_calibrations(old, new))
    assert "removed: gripper" in text


def test_swapped_servo_id_appears_in_the_diff():
    old = _load("follower_main")
    new = dict(old)
    new["elbow_flex"] = replace(old["elbow_flex"], id=old["wrist_flex"].id)
    diff = diff_calibrations(old, new)
    change = next(c for c in diff.changes if c.field == "id")
    assert (change.joint, change.old, change.new) == ("elbow_flex", 3, 4)
    assert "elbow_flex  id" in format_diff(diff)


def test_added_and_removed_lines_in_table():
    old = _load("follower_main")
    new = dict(old)
    new["extra"] = replace(new.pop("gripper"), id=7)
    new["elbow_flex"] = replace(old["elbow_flex"], range_min=1000)
    lines = format_diff(diff_calibrations(old, new)).splitlines()
    assert lines[-2:] == ["removed: gripper", "added: extra"]
    assert any("elbow_flex" in line for line in lines)


def test_diff_is_immutable():
    diff = diff_calibrations(_load("follower_main"), _load("follower_recalibrated"))
    assert isinstance(diff.changes, tuple)
    assert isinstance(diff.added, tuple) and isinstance(diff.removed, tuple)
