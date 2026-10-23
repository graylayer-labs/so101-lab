"""Tests for so101-teleop. Tmp workspaces with fixture calibrations; no hardware."""

import json
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from hw_setup.lerobot_argv import format_command, teleoperate_argv
from hw_setup.teleop import main
from so101.machine_config import load_machine_config

REPO = Path(__file__).parents[3]
EXAMPLE = REPO / "configs" / "example.yaml"
ARMS = ("leader", "follower")


@pytest.fixture
def root(tmp_path: Path) -> Path:
    for arm in ARMS:
        target = tmp_path / "hardware" / "calibration" / arm
        target.mkdir(parents=True)
        shutil.copy(REPO / "hardware" / "calibration" / arm / "main.json", target)
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs" / "local.yaml").write_text(EXAMPLE.read_text())
    return tmp_path


def calib(root: Path, arm: str) -> Path:
    return root / "hardware" / "calibration" / arm / "main.json"


class Runner:
    def __init__(self, code: int = 0) -> None:
        self.calls: list[list[str]] = []
        self.code = code

    def __call__(self, argv: list[str]) -> int:
        self.calls.append(argv)
        return self.code


def expected(root: Path, **kwargs: bool) -> list[str]:
    config = load_machine_config(root / "configs" / "local.yaml")
    return teleoperate_argv(config, root.resolve(), **kwargs)


def test_runs_the_default_command(root: Path) -> None:
    runner = Runner()
    assert main([], runner=runner, root=root) == 0
    assert runner.calls == [expected(root, cameras=True, display_data=False)]


def test_runner_exit_code_is_returned(root: Path) -> None:
    assert main([], runner=Runner(4), root=root) == 4


@pytest.mark.parametrize(
    ("flags", "cameras", "display"),
    [
        (["--no-cameras"], False, False),
        (["--cameras"], True, False),
        (["--display"], True, True),
        (["--no-cameras", "--display"], False, True),
    ],
)
def test_flags_reach_the_argv(
    root: Path, flags: list[str], cameras: bool, display: bool
) -> None:
    runner = Runner()
    main(flags, runner=runner, root=root)
    assert runner.calls == [expected(root, cameras=cameras, display_data=display)]


def test_no_cameras_drops_the_cameras_flag(root: Path) -> None:
    runner = Runner()
    main(["--no-cameras"], runner=runner, root=root)
    assert not any(a.startswith("--robot.cameras") for a in runner.calls[0])


def test_dry_run_prints_the_command_and_runs_nothing(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = Runner()
    assert main(["--dry-run"], runner=runner, root=root) == 0
    out = capsys.readouterr().out
    assert runner.calls == []
    assert format_command(expected(root, cameras=True, display_data=False)) in out
    assert "calibration" in out


def break_range(path: Path) -> None:
    data = json.loads(path.read_text())
    data["elbow_flex"]["range_min"] = data["elbow_flex"]["range_max"] - 50
    path.write_text(json.dumps(data))


def not_json(path: Path) -> None:
    path.write_text("{ nope")


def drop_joint(path: Path) -> None:
    data = json.loads(path.read_text())
    del data["gripper"]
    path.write_text(json.dumps(data))


def delete(path: Path) -> None:
    path.unlink()


@pytest.mark.parametrize("dry_run", [False, True])
@pytest.mark.parametrize("arm", ARMS)
@pytest.mark.parametrize(
    ("damage", "problem"),
    [
        (delete, "missing"),
        (break_range, "range_width"),
        (drop_joint, "gripper"),
        (not_json, "not valid"),
    ],
)
def test_bad_calibration_refuses_even_in_dry_run(
    root: Path,
    capsys: pytest.CaptureFixture[str],
    arm: str,
    damage: Callable[[Path], None],
    problem: str,
    dry_run: bool,
) -> None:
    damage(calib(root, arm))
    runner = Runner()
    code = main(["--dry-run"] if dry_run else [], runner=runner, root=root)
    err = capsys.readouterr().err
    assert code == 1
    assert runner.calls == []
    assert arm in err
    assert problem in err


def test_unreadable_calibration_file_is_refused_without_a_traceback(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = calib(root, "follower")
    path.chmod(0)
    try:
        runner = Runner()
        code = main([], runner=runner, root=root)
    finally:
        path.chmod(0o644)
    err = capsys.readouterr().err
    assert code == 1
    assert runner.calls == []
    assert "follower" in err
    assert "cannot be read" in err


def test_both_bad_arms_are_both_named(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    delete(calib(root, "leader"))
    break_range(calib(root, "follower"))
    assert main([], runner=Runner(), root=root) == 1
    err = capsys.readouterr().err
    assert "leader" in err and "follower" in err


def test_calibration_id_comes_from_the_config(root: Path) -> None:
    other = root / "configs" / "local.yaml"
    other.write_text(EXAMPLE.read_text().replace("id: main", "id: spare"))
    runner = Runner()
    assert main([], runner=runner, root=root) == 1
    for arm in ARMS:
        shutil.copy(calib(root, arm), calib(root, arm).with_name("spare.json"))
    assert main([], runner=runner, root=root) == 0


def test_explicit_config_path(
    root: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    other = tmp_path_factory.mktemp("cfg") / "mine.yaml"
    other.write_text(EXAMPLE.read_text().replace("usbmodem0000000001", "usbmodemZZZ"))
    runner = Runner()
    assert main(["--config", str(other)], runner=runner, root=root) == 0
    assert "--teleop.port=/dev/cu.usbmodemZZZ" in runner.calls[0]


def test_missing_config_fails_with_a_hint(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (root / "configs" / "local.yaml").unlink()
    runner = Runner()
    assert main([], runner=runner, root=root) == 1
    err = capsys.readouterr().err
    assert "so101-find-ports" in err and "example.yaml" in err
    assert runner.calls == []
