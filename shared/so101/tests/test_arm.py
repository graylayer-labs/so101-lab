import pytest

from so101.arm import JOINT_NAMES, ArmConfig, ArmRole


def test_joint_names_match_lerobot_so101_order():
    assert JOINT_NAMES == (
        "shoulder_pan",
        "shoulder_lift",
        "elbow_flex",
        "wrist_flex",
        "wrist_roll",
        "gripper",
    )


def test_arm_config_defaults_to_all_joints():
    arm = ArmConfig(arm_id="main", role=ArmRole.FOLLOWER)
    assert arm.joints == JOINT_NAMES
    assert arm.motor_ids == {name: i for i, name in enumerate(JOINT_NAMES, start=1)}


def test_arm_role_parses_from_string():
    assert ArmRole("leader") is ArmRole.LEADER


def test_arm_config_rejects_unknown_joint():
    with pytest.raises(ValueError, match="unknown joint"):
        ArmConfig(arm_id="main", role=ArmRole.LEADER, joints=("shoulder_pan", "elbow"))


def test_arm_config_rejects_empty_id():
    with pytest.raises(ValueError, match="arm_id"):
        ArmConfig(arm_id="", role=ArmRole.LEADER)
