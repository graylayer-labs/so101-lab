"""Tests for the LeRobot argv builder.

The snapshot tests pin the exact command built from configs/example.yaml.
The parse tests feed each argv to LeRobot 0.6.1's own draccus parser, in
process, so a wrong flag name or a bad cameras dict fails here. Parsing only
builds config dataclasses: no robot is made and no serial port is opened.
"""

from pathlib import Path

import draccus
import pytest
from lerobot.robots.so_follower import SOFollowerRobotConfig
from lerobot.scripts.lerobot_calibrate import CalibrateConfig
from lerobot.scripts.lerobot_record import RecordConfig
from lerobot.scripts.lerobot_setup_motors import SetupConfig
from lerobot.scripts.lerobot_teleoperate import TeleoperateConfig
from lerobot.teleoperators.so_leader import SOLeaderTeleopConfig

from hw_setup.lerobot_argv import (
    CalibrationRootError,
    calibrate_argv,
    format_command,
    record_argv,
    setup_motors_argv,
    teleoperate_argv,
)
from so101.arm import ArmRole
from so101.machine_config import load_machine_config

REPO = Path(__file__).parents[3]
CONFIG = load_machine_config(REPO / "configs" / "example.yaml")
# The workspace root: builders reject a root without hardware/calibration/.
ROOT = REPO.resolve()

FOLLOWER = [
    "--robot.type=so101_follower",
    "--robot.port=/dev/cu.usbmodem0000000002",
    "--robot.id=main",
    f"--robot.calibration_dir={ROOT}/hardware/calibration/follower",
]
LEADER = [
    "--teleop.type=so101_leader",
    "--teleop.port=/dev/cu.usbmodem0000000001",
    "--teleop.id=main",
    f"--teleop.calibration_dir={ROOT}/hardware/calibration/leader",
]
CAMERAS = (
    "--robot.cameras={"
    "front: {type: opencv, index_or_path: 0, width: 640, height: 480, fps: 30}, "
    "wrist: {type: opencv, index_or_path: 1, width: 640, height: 480, fps: 30}}"
)


def test_setup_motors_follower_snapshot():
    argv = setup_motors_argv(CONFIG, ArmRole.FOLLOWER, ROOT)
    assert argv == ["lerobot-setup-motors", *FOLLOWER]


def test_setup_motors_leader_snapshot():
    argv = setup_motors_argv(CONFIG, ArmRole.LEADER, ROOT)
    assert argv == ["lerobot-setup-motors", *LEADER]


def test_calibrate_follower_snapshot():
    argv = calibrate_argv(CONFIG, ArmRole.FOLLOWER, ROOT)
    assert argv == ["lerobot-calibrate", *FOLLOWER]


def test_calibrate_leader_snapshot():
    argv = calibrate_argv(CONFIG, ArmRole.LEADER, ROOT)
    assert argv == ["lerobot-calibrate", *LEADER]


def test_teleoperate_snapshot():
    argv = teleoperate_argv(CONFIG, ROOT)
    assert argv == ["lerobot-teleoperate", *FOLLOWER, CAMERAS, *LEADER]


def test_teleoperate_display_data_and_no_cameras():
    argv = teleoperate_argv(CONFIG, ROOT, cameras=False, display_data=True)
    assert argv == ["lerobot-teleoperate", *FOLLOWER, *LEADER, "--display_data=true"]


def test_record_snapshot():
    argv = record_argv(
        CONFIG,
        ROOT,
        repo_id="graylayer/so101-pick-cube",
        single_task="Pick up the red cube",
        num_episodes=10,
        dataset_root=Path("/data/so101-pick-cube"),
        episode_time_s=30,
        reset_time_s=10,
        fps=30,
        push_to_hub=False,
    )
    assert argv == [
        "lerobot-record",
        *FOLLOWER,
        CAMERAS,
        *LEADER,
        "--dataset.repo_id=graylayer/so101-pick-cube",
        "--dataset.single_task=Pick up the red cube",
        "--dataset.num_episodes=10",
        "--dataset.root=/data/so101-pick-cube",
        "--dataset.episode_time_s=30",
        "--dataset.reset_time_s=10",
        "--dataset.fps=30",
        "--dataset.push_to_hub=false",
    ]


def test_record_omits_unset_options():
    argv = record_argv(CONFIG, ROOT, repo_id="a/b", single_task="Task", num_episodes=1)
    assert argv == [
        "lerobot-record",
        *FOLLOWER,
        CAMERAS,
        *LEADER,
        "--dataset.repo_id=a/b",
        "--dataset.single_task=Task",
        "--dataset.num_episodes=1",
    ]


def test_record_resume_no_stamp_and_no_cameras():
    argv = record_argv(
        CONFIG,
        ROOT,
        repo_id="a/b",
        single_task="Task",
        num_episodes=1,
        cameras=False,
        no_stamp=True,
        resume=True,
    )
    assert argv == [
        "lerobot-record",
        *FOLLOWER,
        *LEADER,
        "--dataset.repo_id=a/b",
        "--dataset.single_task=Task",
        "--dataset.num_episodes=1",
        "--dataset.no_stamp=true",
        "--resume=true",
    ]


def test_relative_repo_root_is_resolved(monkeypatch):
    """A wrapper run from projects/hw-setup/ with Path("..") must still point
    LeRobot at the real calibration files, or it silently recalibrates."""
    monkeypatch.chdir(REPO / "projects" / "hw-setup")
    argv = calibrate_argv(CONFIG, ArmRole.LEADER, Path("../.."))
    assert f"--teleop.calibration_dir={ROOT}/hardware/calibration/leader" in argv


def test_wrong_repo_root_is_rejected(tmp_path):
    with pytest.raises(CalibrationRootError, match="hardware/calibration"):
        calibrate_argv(CONFIG, ArmRole.LEADER, tmp_path)


def test_wrong_relative_repo_root_is_rejected(monkeypatch):
    monkeypatch.chdir(REPO / "projects" / "hw-setup")
    with pytest.raises(CalibrationRootError, match="hardware/calibration"):
        teleoperate_argv(CONFIG, Path("."))


def test_format_command_quotes_for_the_shell():
    argv = ["lerobot-record", "--dataset.single_task=Pick it up", CAMERAS]
    text = format_command(argv)
    assert text.startswith("lerobot-record '--dataset.single_task=Pick it up' ")
    assert text.endswith(f"'{CAMERAS}'")


# --- LeRobot 0.6.1 accepts every argv ------------------------------------


def parse(config_class, argv):
    assert argv[0].startswith("lerobot-")
    return draccus.parse(config_class=config_class, args=argv[1:])


@pytest.mark.parametrize("role", list(ArmRole))
def test_lerobot_parses_setup_motors_and_calibrate(role):
    for build, config_class in (
        (setup_motors_argv, SetupConfig),
        (calibrate_argv, CalibrateConfig),
    ):
        cfg = parse(config_class, build(CONFIG, role, ROOT))
        assert cfg.device.id == "main"
        assert cfg.device.calibration_dir == ROOT / "hardware/calibration" / role


def test_lerobot_parses_teleoperate():
    cfg = parse(TeleoperateConfig, teleoperate_argv(CONFIG, ROOT, display_data=True))
    # so101_* and so100_* name the same classes; `.type` reports so100_*.
    assert isinstance(cfg.robot, SOFollowerRobotConfig)
    assert cfg.robot.port == "/dev/cu.usbmodem0000000002"
    assert isinstance(cfg.teleop, SOLeaderTeleopConfig)
    assert cfg.teleop.port == "/dev/cu.usbmodem0000000001"
    assert cfg.display_data is True
    front = cfg.robot.cameras["front"]
    assert front.type == "opencv"
    assert (front.index_or_path, front.width, front.height, front.fps) == (
        0,
        640,
        480,
        30,
    )
    assert cfg.robot.cameras["wrist"].index_or_path == 1


def test_lerobot_parses_record():
    argv = record_argv(
        CONFIG,
        ROOT,
        repo_id="a/b",
        single_task="Pick up the red cube",
        num_episodes=3,
        dataset_root=Path("/data/x"),
        episode_time_s=20,
        reset_time_s=5,
        fps=30,
        push_to_hub=False,
        no_stamp=True,
        resume=True,
    )
    cfg = parse(RecordConfig, argv)
    assert cfg.resume is True
    assert cfg.dataset.no_stamp is True
    assert cfg.dataset.single_task == "Pick up the red cube"
    assert cfg.dataset.num_episodes == 3
    assert Path(cfg.dataset.root) == Path("/data/x")
    assert cfg.dataset.push_to_hub is False
    assert set(cfg.robot.cameras) == {"front", "wrist"}
    assert cfg.teleop is not None and cfg.teleop.id == "main"


def test_lerobot_rejects_an_unknown_flag():
    """Guards the parse tests: draccus must fail on a misspelt flag."""
    argv = [*calibrate_argv(CONFIG, ArmRole.LEADER, ROOT), "--teleop.calib_dir=x"]
    with pytest.raises(SystemExit):
        parse(CalibrateConfig, argv)


def test_lerobot_rejects_an_unknown_record_flag():
    """The real RecordConfig checks --dataset.* names too."""
    argv = record_argv(CONFIG, ROOT, repo_id="a/b", single_task="T", num_episodes=1)
    with pytest.raises(SystemExit):
        parse(RecordConfig, [*argv, "--dataset.push_to_hubb=false"])
