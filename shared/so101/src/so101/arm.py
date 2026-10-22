"""SO-101 joint names and a typed arm config."""

from dataclasses import dataclass, field
from enum import StrEnum

# Joint names in motor-id order (id 1 to 6), as LeRobot names them for SO-101.
JOINT_NAMES: tuple[str, ...] = (
    "shoulder_pan",
    "shoulder_lift",
    "elbow_flex",
    "wrist_flex",
    "wrist_roll",
    "gripper",
)


class ArmRole(StrEnum):
    """Which arm of the pair: the leader is moved by hand, the follower copies."""

    LEADER = "leader"
    FOLLOWER = "follower"


@dataclass(frozen=True)
class ArmConfig:
    """One physical arm: its id, its role and the joints it drives."""

    arm_id: str
    role: ArmRole
    joints: tuple[str, ...] = field(default=JOINT_NAMES)

    def __post_init__(self) -> None:
        if not self.arm_id:
            raise ValueError("arm_id must be a non-empty string")
        unknown = [name for name in self.joints if name not in JOINT_NAMES]
        if unknown:
            raise ValueError(f"unknown joint(s): {', '.join(unknown)}")

    @property
    def motor_ids(self) -> dict[str, int]:
        """Servo bus id for each joint (1 to 6, in JOINT_NAMES order)."""
        return {name: JOINT_NAMES.index(name) + 1 for name in self.joints}
