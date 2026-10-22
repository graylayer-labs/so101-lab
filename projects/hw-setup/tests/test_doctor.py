"""Tests for so101-doctor. Injected fakes; no port, camera or LeRobot is opened."""

import shutil
import tomllib
from pathlib import Path

import pytest

from hw_setup import doctor
from hw_setup.doctor import LEROBOT_PIN, CameraOpener, main

REPO = Path(__file__).parents[3]
EXAMPLE = REPO / "configs" / "example.yaml"
LEADER = "/dev/cu.usbmodem0000000001"
FOLLOWER = "/dev/cu.usbmodem0000000002"
TTY = EXAMPLE.read_text().replace("/dev/cu.", "/dev/tty.")


@pytest.fixture
def root(tmp_path: Path) -> Path:
    for arm in ("leader", "follower"):
        target = tmp_path / "hardware" / "calibration" / arm
        target.mkdir(parents=True)
        shutil.copy(REPO / "hardware" / "calibration" / arm / "main.json", target)
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs" / "local.yaml").write_text(EXAMPLE.read_text())
    return tmp_path


def run(
    root: Path | None,
    argv: list[str] | None = None,
    *,
    ports: list[str] | None = None,
    version: str | None = LEROBOT_PIN,
    cameras: list[str] | None = None,
    opener: CameraOpener | None = None,
    platform: str = "linux",
    capsys: pytest.CaptureFixture[str],
) -> tuple[int, str]:
    code = main(
        argv or [],
        root=root,
        port_lister=lambda: [LEADER, FOLLOWER] if ports is None else ports,
        version_getter=lambda: version,
        camera_lister=lambda: ["Cam A", "Cam B"] if cameras is None else cameras,
        camera_opener=opener or (lambda index: None),
        platform=platform,
    )
    return code, capsys.readouterr().out


def line_for(out: str, name: str) -> str:
    return next(line for line in out.splitlines() if f" {name}:" in line)


def test_pin_matches_pyproject() -> None:
    data = tomllib.loads((REPO / "projects/hw-setup/pyproject.toml").read_text())
    assert f"lerobot[feetech]=={LEROBOT_PIN}" in data["project"]["dependencies"]


def test_all_pass_exits_zero(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = run(root, capsys=capsys)
    assert code == 0
    assert "FAIL" not in out
    assert out.count("PASS") >= 6


def test_wrong_lerobot_version_fails_with_fix(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out = run(root, version="0.5.0", capsys=capsys)
    assert code == 1
    assert line_for(out, "lerobot").startswith("FAIL")
    assert "0.5.0" in out and LEROBOT_PIN in out
    assert "uv sync --dev --all-packages" in out


def test_lerobot_missing_fails(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = run(root, version=None, capsys=capsys)
    assert code == 1
    assert "not installed" in line_for(out, "lerobot")


def test_missing_config_fails_with_fix(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (root / "configs" / "local.yaml").unlink()
    code, out = run(root, capsys=capsys)
    assert code == 1
    assert line_for(out, "config").startswith("FAIL")
    assert "so101-find-ports" in out and "configs/example.yaml" in out
    # dependent checks do not crash
    assert line_for(out, "ports").startswith("WARN")


def test_invalid_config_fails(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (root / "configs" / "local.yaml").write_text("arms: {}\n")
    code, out = run(root, capsys=capsys)
    assert code == 1
    assert "arms.leader" in line_for(out, "config")


def test_explicit_config_path(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = run(root, ["--config", str(EXAMPLE)], capsys=capsys)
    assert code == 0
    assert str(EXAMPLE) in out


def test_workspace_not_found(capsys: pytest.CaptureFixture[str], monkeypatch) -> None:
    def boom(start: Path | None = None) -> Path:
        raise doctor.WorkspaceError("no workspace root found")

    monkeypatch.setattr(doctor, "find_workspace_root", boom)
    code, out = run(None, capsys=capsys)
    assert code == 1
    assert line_for(out, "workspace").startswith("FAIL")


def test_missing_port_fails_naming_role(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out = run(root, ports=[LEADER], capsys=capsys)
    assert code == 1
    assert "follower" in out and FOLLOWER in out
    assert "so101-find-ports" in out


def test_no_ports_at_all(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = run(root, ports=[], capsys=capsys)
    assert code == 1
    assert out.count("so101-find-ports") >= 1


def test_macos_tty_config_matches_cu_listing_and_warns(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Real pyserial on macOS lists only cu.* names.
    (root / "configs" / "local.yaml").write_text(TTY)
    code, out = run(root, platform="darwin", capsys=capsys)
    assert code == 0
    assert line_for(out, "ports").startswith("WARN")
    assert "matched" in out and LEADER in out
    assert "accepts both" in out


def test_macos_tty_config_with_nothing_listed_fails(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (root / "configs" / "local.yaml").write_text(TTY)
    code, out = run(root, platform="darwin", ports=[], capsys=capsys)
    assert code == 1
    assert line_for(out, "ports").startswith("FAIL")


def test_macos_cu_port_passes(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = run(root, platform="darwin", capsys=capsys)
    assert code == 0
    assert line_for(out, "ports").startswith("PASS")


def test_skipped_checks_have_fix_lines(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (root / "configs" / "local.yaml").unlink()
    _code, out = run(root, capsys=capsys)
    skipped = out.split("WARN  ports:")[1]
    assert "fix:" in skipped.split("WARN  calibration:")[0]
    assert "fix:" in skipped.split("WARN  calibration:")[1].split("WARN  cameras:")[0]
    assert "fix:" in skipped.split("WARN  cameras:")[1]


def test_config_fix_names_the_given_path(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = root / "elsewhere.yaml"
    code, out = run(root, ["--config", str(missing)], capsys=capsys)
    assert code == 1
    assert f"cp configs/example.yaml {missing}" in out


def test_camera_check_says_it_compares_counts() -> None:
    assert "compares counts only" in Path(doctor.__file__).read_text()


def test_bad_calibration_fails_with_command(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (root / "hardware/calibration/follower/main.json").unlink()
    code, out = run(root, capsys=capsys)
    assert code == 1
    assert line_for(out, "calibration").startswith("FAIL")
    assert "follower arm (main): calibration missing" in out
    assert "so101-calibrate --role follower" in out
    assert "so101-calibrate --role leader" not in out


def test_cameras_listed_not_opened_by_default(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    opened: list[int] = []

    def opener(index: int) -> str | None:
        opened.append(index)
        return None

    code, out = run(root, opener=opener, capsys=capsys)
    assert code == 0
    assert opened == []
    assert "Cam A" in out and "Cam B" in out


def test_fewer_cameras_than_configured_warns(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out = run(root, cameras=["Cam A"], capsys=capsys)
    assert code == 0
    assert line_for(out, "cameras").startswith("WARN")
    assert "2 configured" in out


def test_open_cameras_opens_each_configured_index(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    opened: list[int] = []

    def opener(index: int) -> str | None:
        opened.append(index)
        return None

    code, out = run(root, ["--open-cameras"], opener=opener, capsys=capsys)
    assert code == 0
    assert opened == [0, 1]


def test_open_camera_failure_fails_with_macos_hint(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out = run(
        root,
        ["--open-cameras"],
        opener=lambda index: "could not read a frame" if index == 1 else None,
        platform="darwin",
        capsys=capsys,
    )
    assert code == 1
    assert "wrist" in out and "index 1" in out
    assert "System Settings" in out and "Privacy & Security" in out
    assert "Camera" in out


def test_open_camera_failure_linux_has_no_macos_hint(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out = run(
        root, ["--open-cameras"], opener=lambda index: "busy", capsys=capsys
    )
    assert code == 1
    assert "System Settings" not in out


def test_macos_camera_list_parses_system_profiler() -> None:
    sample = (
        '{"SPCameraDataType": [{"_name": "FaceTime HD Camera"}, {"_name": "USB Cam"}]}'
    )
    assert doctor.parse_system_profiler(sample) == ["FaceTime HD Camera", "USB Cam"]
    assert doctor.parse_system_profiler("not json") == []
    assert doctor.parse_system_profiler("{}") == []


def test_never_compares_type_strings() -> None:
    assert ".type" not in Path(doctor.__file__).read_text()
