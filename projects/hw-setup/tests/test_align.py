"""Tests for hw_setup.align and so101-align. Fake buses (conftest.py); no port."""

import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from hw_setup import align
from hw_setup.align import Alignment, JointGap, check_alignment, main, make_devices
from so101.arm import ArmRole
from so101.machine_config import load_machine_config

REPO = Path(__file__).parents[3]
EXAMPLE = REPO / "configs" / "example.yaml"
# The arms' first calibration, frozen: the hand-computed degrees below use its
# ranges, so a recalibration of the real arms must not change these tests.
FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 23, 9, 30, 0, tzinfo=UTC)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    for arm in ("leader", "follower"):
        target = tmp_path / "hardware" / "calibration" / arm
        target.mkdir(parents=True)
        shutil.copy(FIXTURES / f"{arm}_main.json", target / "main.json")
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs" / "local.yaml").write_text(EXAMPLE.read_text())
    return tmp_path


def config_of(root: Path):
    return load_machine_config(root / "configs" / "local.yaml")


def gap(alignment: Alignment, joint: str) -> JointGap:
    return next(j for j in alignment.joints if j.joint == joint)


# --- building the LeRobot objects -----------------------------------------


def test_devices_come_from_the_wrappers_config_and_calibration(root: Path) -> None:
    devices = make_devices(config_of(root), root)
    for role in ArmRole:
        device = devices[role]
        assert device.calibration_dir == root.resolve() / "hardware/calibration" / role
        assert device.id == "main"
        assert set(device.bus.calibration) == set(align.JOINTS)
        assert not device.bus.is_connected
    assert devices[ArmRole.FOLLOWER].bus.port == "/dev/cu.usbmodem0000000002"
    assert devices[ArmRole.LEADER].bus.port == "/dev/cu.usbmodem0000000001"


def test_the_guard_stops_a_real_bus_from_opening_its_port(root: Path) -> None:
    """Guards every other test: the conftest patch must reach pyserial."""
    # ``make_devices`` here is the real one, imported before any monkeypatch.
    bus = make_devices(config_of(root), root)[ArmRole.LEADER].bus
    with pytest.raises(AssertionError, match="serial port"):
        bus.port_handler.openPort()


def test_units_are_teleops_degrees_and_gripper_percent(root: Path, fake_arms) -> None:
    factory, _ = fake_arms()
    alignment = check_alignment(config_of(root), root, device_factory=factory)
    units = {j.joint: j.unit for j in alignment.joints}
    assert units == {**dict.fromkeys(align.JOINTS[:5], "deg"), "gripper": "%"}


# --- reading -------------------------------------------------------------


def test_reads_calibrated_positions_and_their_difference(root: Path, fake_arms) -> None:
    factory, _ = fake_arms(
        leader={"elbow_flex": 12.0, "wrist_roll": 90.0, "gripper": 30.0},
        follower={"elbow_flex": 0.0, "wrist_roll": -8.0, "gripper": 25.0},
    )
    alignment = check_alignment(config_of(root), root, device_factory=factory)
    elbow = gap(alignment, "elbow_flex")
    # One encoder tick is 360/4095 = 0.088 degrees.
    assert elbow.leader == pytest.approx(12.0, abs=0.1)
    assert elbow.follower == pytest.approx(0.0, abs=0.1)
    assert elbow.diff == pytest.approx(12.0, abs=0.2)
    assert gap(alignment, "wrist_roll").diff == pytest.approx(98.0, abs=0.2)
    assert gap(alignment, "gripper").diff == pytest.approx(5.0, abs=0.2)
    assert [j.joint for j in alignment.joints] == list(align.JOINTS)


def test_raw_ticks_read_as_hand_computed_degrees_and_percent(
    root: Path, fake_arms
) -> None:
    """Expected values worked out by hand, not through LeRobot's conversion.

    lerobot 0.6.1 motors/motors_bus.py L874-877 (DEGREES) and L871-873
    (RANGE_0_100), drive_mode 0:

        degrees = (raw - (range_min + range_max) / 2) * 360 / (4096 - 1)
        percent = (raw - range_min) / (range_max - range_min) * 100

    Homing does not enter: the motor applies Homing_Offset itself and
    reports Present_Position = Actual_Position - Homing_Offset
    (motors/feetech/feetech.py L278-282), so the raw tick read is already
    homed. Ranges are those of tests/fixtures/<arm>_main.json.
    """
    factory, _ = fake_arms(
        raw_ticks={
            # elbow_flex: leader range 734-3003 (mid 1868.5), follower
            # 1132-3102 (mid 2117). gripper: leader 1269-2468, follower
            # 1433-2870.
            ArmRole.LEADER: {"elbow_flex": 2005, "gripper": 1509},
            ArmRole.FOLLOWER: {"elbow_flex": 2253, "gripper": 1720},
        }
    )
    alignment = check_alignment(config_of(root), root, device_factory=factory)
    elbow = gap(alignment, "elbow_flex")
    gripper = gap(alignment, "gripper")
    # (2005 - 1868.5) * 360 / 4095 = 136.5 * 360 / 4095 = 12.0
    assert elbow.leader == pytest.approx(12.0, abs=1e-6)
    # (2253 - 2117) * 360 / 4095 = 48960 / 4095 = 11.95604...
    assert elbow.follower == pytest.approx(11.956044, abs=1e-5)
    assert elbow.diff == pytest.approx(0.043956, abs=1e-5)
    assert elbow.unit == "deg"
    # (1509 - 1269) / 1199 * 100 = 20.01668...; (1720 - 1433) / 1437 * 100
    # = 19.97216...
    assert gripper.leader == pytest.approx(20.016681, abs=1e-5)
    assert gripper.follower == pytest.approx(19.972164, abs=1e-5)
    assert gripper.unit == "%"


def test_nothing_is_ever_written_to_either_arm(root: Path, fake_arms) -> None:
    factory, devices = fake_arms(leader={"elbow_flex": 40.0})
    check_alignment(config_of(root), root, device_factory=factory)
    for role in ArmRole:
        bus = devices[role].bus
        assert bus.writes == []  # no Goal_Position, no Torque_Enable, nothing
        assert bus.sync_reads == ["Present_Position"]
        assert bus.port_handler.calls[-1] == "closePort"
        assert not bus.is_connected


def test_disconnect_runs_when_a_read_fails(root: Path, fake_arms) -> None:
    factory, devices = fake_arms(
        fail_sync_read={ArmRole.FOLLOWER: ConnectionError("no status packet")}
    )
    with pytest.raises(ConnectionError, match="no status packet"):
        check_alignment(config_of(root), root, device_factory=factory)
    for role in ArmRole:
        bus = devices[role].bus
        assert not bus.is_connected
        assert bus.writes == []
        assert "clearPort" not in bus.port_handler.calls  # disable_torque=False


def test_first_arm_is_closed_when_the_second_cannot_connect(
    root: Path, fake_arms
) -> None:
    factory, devices = fake_arms(open_ok={ArmRole.FOLLOWER: False})
    with pytest.raises(ConnectionError):
        check_alignment(config_of(root), root, device_factory=factory)
    leader = devices[ArmRole.LEADER].bus
    assert leader.port_handler.calls[-1] == "closePort"
    assert not leader.is_connected
    assert all(devices[r].bus.writes == [] for r in ArmRole)


def test_motors_that_disagree_with_the_file_are_reported(root: Path, fake_arms) -> None:
    devices = make_devices(config_of(root), root)
    stored = dict(devices[ArmRole.FOLLOWER].bus.calibration)
    elbow = stored["elbow_flex"]
    stored["elbow_flex"] = type(elbow)(
        elbow.id, elbow.drive_mode, elbow.homing_offset + 40, elbow.range_min,
        elbow.range_max,
    )  # fmt: skip
    factory, _ = fake_arms(motor_calibration={ArmRole.FOLLOWER: stored})
    alignment = check_alignment(config_of(root), root, device_factory=factory)
    assert alignment.motors_match_file == {
        ArmRole.LEADER: True,
        ArmRole.FOLLOWER: False,
    }
    assert not alignment.ok(5.0)


# --- threshold -----------------------------------------------------------


def joint(diff: float, unit: str = "deg", name: str = "elbow_flex") -> JointGap:
    return JointGap(name, leader=diff, follower=0.0, unit=unit)


def alignment_of(*joints: JointGap) -> Alignment:
    return Alignment(tuple(joints), dict.fromkeys(ArmRole, True))


@pytest.mark.parametrize(
    ("diff", "over"),
    [(0.0, False), (4.9, False), (5.0, False), (5.01, True), (-5.01, True)],
)
def test_threshold_is_on_the_absolute_difference(diff: float, over: bool) -> None:
    alignment = alignment_of(joint(diff))
    assert bool(alignment.over(5.0)) is over
    assert alignment.ok(5.0) is not over


def test_every_joint_over_is_listed() -> None:
    alignment = alignment_of(
        joint(12.0, name="elbow_flex"),
        joint(1.0, name="wrist_flex"),
        joint(-98.0, name="wrist_roll"),
    )
    assert [j.joint for j in alignment.over(5.0)] == ["elbow_flex", "wrist_roll"]


def test_wrist_roll_does_not_wrap_at_180(root: Path, fake_arms) -> None:
    """+179 and -179 degrees are 2 degrees apart on a circle, but the
    follower's position servo moves the long way, 358 degrees, through the
    raw 0-4095 range: the difference must not wrap."""
    factory, _ = fake_arms(
        leader={"wrist_roll": 179.0}, follower={"wrist_roll": -179.0}
    )
    alignment = check_alignment(config_of(root), root, device_factory=factory)
    roll = gap(alignment, "wrist_roll")
    assert roll.diff == pytest.approx(358.0, abs=0.2)
    assert [j.joint for j in alignment.over(5.0)] == ["wrist_roll"]


# --- table and record ------------------------------------------------------


def test_table_names_each_joint_and_marks_the_ones_over() -> None:
    alignment = alignment_of(
        joint(12.0, name="elbow_flex"), joint(2.0, unit="%", name="gripper")
    )
    table = align.format_table(alignment, 5.0)
    elbow = next(line for line in table.splitlines() if "elbow_flex" in line)
    gripper = next(line for line in table.splitlines() if "gripper" in line)
    assert "OVER" in elbow and "+12.0" in elbow
    assert "ok" in gripper and "%" in gripper


def test_record_is_written_under_outputs_hw(root: Path) -> None:
    alignment = alignment_of(joint(12.0))
    path = align.write_record(root, alignment, 5.0, now=NOW)
    assert path == root / "outputs" / "hw" / "alignment-20261023T093000Z.json"
    data = json.loads(path.read_text())
    assert data["time_utc"] == "2026-10-23T09:30:00Z"
    assert data["limit"] == 5.0
    assert data["aligned"] is False
    assert data["joints"]["elbow_flex"] == {
        "leader": 12.0,
        "follower": 0.0,
        "diff": 12.0,
        "unit": "deg",
        "over": True,
    }
    assert data["motors_match_file"] == {"leader": True, "follower": True}


def test_outputs_are_gitignored() -> None:
    done = subprocess.run(
        ["git", "check-ignore", "-q", "outputs/hw/alignment-20261023T093000Z.json"],
        cwd=REPO,
        check=False,
    )
    assert done.returncode == 0


# --- so101-align -----------------------------------------------------------


def test_cli_prints_the_table_once_and_writes_the_record(
    root: Path, fake_arms, capsys: pytest.CaptureFixture[str]
) -> None:
    factory, devices = fake_arms()
    code = main([], root=root, device_factory=factory, now=lambda: NOW)
    out = capsys.readouterr().out
    assert code == 0
    assert out.count("shoulder_pan") == 1
    assert "outputs/hw/alignment-20261023T093000Z.json" in out
    assert (root / "outputs/hw/alignment-20261023T093000Z.json").is_file()
    assert all(devices[r].bus.writes == [] for r in ArmRole)


def test_cli_exits_1_when_a_joint_is_over(
    root: Path, fake_arms, capsys: pytest.CaptureFixture[str]
) -> None:
    factory, _ = fake_arms(leader={"elbow_flex": 12.0})
    assert main([], root=root, device_factory=factory, now=lambda: NOW) == 1
    out = capsys.readouterr().out
    assert "elbow_flex" in out and "so101-calibrate" in out


def test_cli_align_max_changes_the_limit(root: Path, fake_arms) -> None:
    factory, _ = fake_arms(leader={"elbow_flex": 12.0})
    argv = ["--align-max", "15"]
    assert main(argv, root=root, device_factory=factory, now=lambda: NOW) == 0


def test_cli_explicit_config(root: Path, fake_arms, tmp_path_factory) -> None:
    other = tmp_path_factory.mktemp("cfg") / "mine.yaml"
    other.write_text(EXAMPLE.read_text().replace("usbmodem0000000001", "usbmodemZZ"))
    factory, devices = fake_arms()
    main(["--config", str(other)], root=root, device_factory=factory, now=lambda: NOW)
    assert devices[ArmRole.LEADER].bus.port == "/dev/cu.usbmodemZZ"


def test_cli_connection_error_is_reported_and_ports_closed(
    root: Path, fake_arms, capsys: pytest.CaptureFixture[str]
) -> None:
    factory, devices = fake_arms(open_ok={ArmRole.LEADER: False})
    assert main([], root=root, device_factory=factory, now=lambda: NOW) == 1
    assert "could not read the arms" in capsys.readouterr().err
    assert not any(devices[r].bus.is_connected for r in ArmRole)


class Sleeper:
    """Stands in for time.sleep; Ctrl-C arrives on call ``stop_at``."""

    def __init__(self, stop_at: int) -> None:
        self.calls: list[float] = []
        self.stop_at = stop_at

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)
        if len(self.calls) == self.stop_at:
            raise KeyboardInterrupt


def test_watch_refreshes_until_ctrl_c_then_cleans_up(
    root: Path, fake_arms, capsys: pytest.CaptureFixture[str]
) -> None:
    factory, devices = fake_arms()
    sleeper = Sleeper(stop_at=3)
    code = main(
        ["--watch"], root=root, device_factory=factory, sleep=sleeper, now=lambda: NOW
    )
    out = capsys.readouterr().out
    assert code == 0
    assert sleeper.calls == [align.WATCH_PERIOD_S] * 3
    assert out.count("shoulder_pan") == 3
    for role in ArmRole:
        bus = devices[role].bus
        assert bus.sync_reads == ["Present_Position"] * 3
        assert bus.handshakes == 1  # connected once, not per refresh
        assert bus.writes == []
        assert not bus.is_connected
    assert (root / "outputs/hw/alignment-20261023T093000Z.json").is_file()


def test_watch_record_is_the_last_reading(root: Path, fake_arms) -> None:
    factory, _ = fake_arms(leader={"elbow_flex": 12.0})
    code = main(
        ["--watch"],
        root=root,
        device_factory=factory,
        sleep=Sleeper(stop_at=1),
        now=lambda: NOW,
    )
    assert code == 1
    data = json.loads((root / "outputs/hw/alignment-20261023T093000Z.json").read_text())
    assert data["joints"]["elbow_flex"]["over"] is True


def test_watch_period_is_about_twice_a_second() -> None:
    assert align.WATCH_PERIOD_S == 0.5
