from pathlib import Path

import pytest

from so101.arm import ArmRole
from so101.machine_config import MachineConfigError, load_machine_config

EXAMPLE = Path(__file__).parents[3] / "configs" / "example.yaml"

GOOD = """
arms:
  leader: {id: main, port: /dev/tty.usbmodem1}
  follower: {id: main, port: /dev/ttyACM0}
cameras:
  front: {index: 0, width: 640, height: 480, fps: 30}
  wrist: {index: 1, width: 640, height: 480, fps: 30}
"""


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "local.yaml"
    path.write_text(text)
    return path


def test_good_file_loads(tmp_path):
    config = load_machine_config(write(tmp_path, GOOD))
    assert config.arms[ArmRole.LEADER].port == "/dev/tty.usbmodem1"
    assert config.arms[ArmRole.FOLLOWER].arm_id == "main"
    assert config.cameras["wrist"].index == 1
    assert config.cameras["front"].fps == 30


def test_example_yaml_passes():
    config = load_machine_config(EXAMPLE)
    assert set(config.arms) == {ArmRole.LEADER, ArmRole.FOLLOWER}
    assert set(config.cameras) == {"front", "wrist"}


def test_missing_key_names_the_key(tmp_path):
    text = GOOD.replace(", fps: 30}\n  wrist", "}\n  wrist", 1)
    with pytest.raises(MachineConfigError, match=r"cameras\.front\.fps"):
        load_machine_config(write(tmp_path, text))


def test_missing_arm_names_the_key(tmp_path):
    text = GOOD.replace("  follower: {id: main, port: /dev/ttyACM0}\n", "")
    with pytest.raises(MachineConfigError, match=r"arms\.follower"):
        load_machine_config(write(tmp_path, text))


def test_bad_port_message_names_cu_as_well_as_tty(tmp_path):
    text = GOOD.replace("/dev/ttyACM0", "usb-port-two")
    with pytest.raises(MachineConfigError) as exc:
        load_machine_config(write(tmp_path, text))
    assert "/dev/cu.usbmodem*" in str(exc.value)
    assert "/dev/tty.usbmodem*" in str(exc.value)


def test_bad_port_pattern_names_the_key(tmp_path):
    text = GOOD.replace("/dev/ttyACM0", "usb-port-two")
    with pytest.raises(MachineConfigError, match=r"arms\.follower\.port"):
        load_machine_config(write(tmp_path, text))


def test_duplicate_camera_index_names_both_cameras(tmp_path):
    text = GOOD.replace("wrist: {index: 1", "wrist: {index: 0")
    with pytest.raises(MachineConfigError, match=r"cameras\.wrist\.index.*front"):
        load_machine_config(write(tmp_path, text))


def test_wrong_type_names_the_key(tmp_path):
    text = GOOD.replace("width: 640", "width: wide", 1)
    with pytest.raises(MachineConfigError, match=r"cameras\.front\.width"):
        load_machine_config(write(tmp_path, text))


def test_missing_file_is_a_clear_error(tmp_path):
    with pytest.raises(MachineConfigError, match="not found"):
        load_machine_config(tmp_path / "nope.yaml")


def test_non_mapping_section_names_the_key(tmp_path):
    text = GOOD.replace("leader: {id: main, port: /dev/tty.usbmodem1}", "leader: 5")
    with pytest.raises(MachineConfigError, match=r"arms\.leader: expected a mapping"):
        load_machine_config(write(tmp_path, text))


def test_zero_width_is_out_of_range(tmp_path):
    text = GOOD.replace("width: 640", "width: 0", 1)
    with pytest.raises(
        MachineConfigError, match=r"cameras\.front\.width: out of range"
    ):
        load_machine_config(write(tmp_path, text))


def test_camera_index_zero_is_allowed(tmp_path):
    assert load_machine_config(write(tmp_path, GOOD)).cameras["front"].index == 0


def test_empty_arm_id_names_the_key(tmp_path):
    text = GOOD.replace("id: main, port: /dev/ttyACM0", 'id: "", port: /dev/ttyACM0')
    with pytest.raises(MachineConfigError, match=r"arms\.follower\.id"):
        load_machine_config(write(tmp_path, text))


def test_invalid_yaml_is_a_clear_error(tmp_path):
    with pytest.raises(MachineConfigError, match="invalid YAML"):
        load_machine_config(write(tmp_path, "arms: [unclosed"))
