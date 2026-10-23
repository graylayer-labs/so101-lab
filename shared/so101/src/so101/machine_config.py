"""Load and validate the machine config (`configs/local.yaml`).

The file lists the serial port of each arm and the settings of each camera.
Every error names the dotted key that is wrong, for example `cameras.front.fps`.
Loading only reads the file; it never opens a serial port or a camera.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from so101.arm import ArmRole

# macOS (/dev/tty.usbmodem*, /dev/cu.usbmodem*), Linux (/dev/ttyACM*, /dev/ttyUSB*)
# and Windows (COM3).
PORT_PATTERN = re.compile(
    r"^(/dev/(tty|cu)\.(usbmodem|usbserial)[\w.-]+|/dev/tty(ACM|USB)\d+|COM\d+)$"
)


class MachineConfigError(ValueError):
    """The machine config file is missing, unreadable or invalid."""


@dataclass(frozen=True)
class ArmPort:
    """Where one arm is connected."""

    arm_id: str
    port: str


@dataclass(frozen=True)
class CameraSettings:
    """One camera's index and capture settings."""

    index: int
    width: int
    height: int
    fps: int


@dataclass(frozen=True)
class MachineConfig:
    """The validated machine config."""

    arms: dict[ArmRole, ArmPort]
    cameras: dict[str, CameraSettings]


def _mapping(value: Any, key: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise MachineConfigError(f"{key}: expected a mapping")
    return value


def _require(section: dict[str, Any], name: str, prefix: str) -> Any:
    if name not in section or section[name] is None:
        raise MachineConfigError(f"{prefix}.{name}: missing")
    return section[name]


def _positive_int(section: dict[str, Any], name: str, prefix: str) -> int:
    value = _require(section, name, prefix)
    if isinstance(value, bool) or not isinstance(value, int):
        raise MachineConfigError(f"{prefix}.{name}: expected an integer, got {value!r}")
    if value < (0 if name == "index" else 1):
        raise MachineConfigError(f"{prefix}.{name}: out of range, got {value}")
    return value


def _parse_arm(raw: Any, role: ArmRole) -> ArmPort:
    prefix = f"arms.{role.value}"
    arm = _mapping(raw, prefix)
    arm_id = _require(arm, "id", prefix)
    if not isinstance(arm_id, str) or not arm_id:
        raise MachineConfigError(f"{prefix}.id: expected a non-empty string")
    port = _require(arm, "port", prefix)
    if not isinstance(port, str) or not PORT_PATTERN.match(port):
        raise MachineConfigError(
            f"{prefix}.port: {port!r} is not a serial port path "
            "(expected /dev/cu.usbmodem*, /dev/tty.usbmodem*, /dev/ttyACM*, "
            "/dev/ttyUSB* or COMn)"
        )
    return ArmPort(arm_id=arm_id, port=port)


def _parse_camera(raw: Any, name: str) -> CameraSettings:
    prefix = f"cameras.{name}"
    camera = _mapping(raw, prefix)
    return CameraSettings(
        index=_positive_int(camera, "index", prefix),
        width=_positive_int(camera, "width", prefix),
        height=_positive_int(camera, "height", prefix),
        fps=_positive_int(camera, "fps", prefix),
    )


def parse_machine_config(data: Any) -> MachineConfig:
    """Validate parsed YAML data and return a MachineConfig."""
    root = _mapping(data, "config")
    arms_raw = _mapping(_require(root, "arms", "config"), "arms")
    arms = {}
    for role in ArmRole:
        if role.value not in arms_raw:
            raise MachineConfigError(f"arms.{role.value}: missing")
        arms[role] = _parse_arm(arms_raw[role.value], role)

    cameras_raw = _mapping(_require(root, "cameras", "config"), "cameras")
    cameras: dict[str, CameraSettings] = {}
    seen: dict[int, str] = {}
    for name, raw in cameras_raw.items():
        camera = _parse_camera(raw, str(name))
        if camera.index in seen:
            raise MachineConfigError(
                f"cameras.{name}.index: {camera.index} is already used by "
                f"cameras.{seen[camera.index]}"
            )
        seen[camera.index] = str(name)
        cameras[str(name)] = camera
    return MachineConfig(arms=arms, cameras=cameras)


def load_machine_config(path: Path) -> MachineConfig:
    """Read and validate a machine config file."""
    try:
        text = path.read_text()
    except FileNotFoundError:
        raise MachineConfigError(f"{path}: not found") from None
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as err:
        raise MachineConfigError(f"{path}: invalid YAML: {err}") from err
    return parse_machine_config(data)
