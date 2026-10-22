"""Tests for so101-calibrate. No hardware: the runner is a fake that writes a file."""

import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from hw_setup.calibrate import backup_path, main
from hw_setup.lerobot_argv import calibrate_argv, format_command
from so101.arm import ArmRole
from so101.machine_config import load_machine_config

EXAMPLE = Path(__file__).parents[3] / "configs" / "example.yaml"
FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 22, 21, 30, 5, tzinfo=UTC)
STAMP = "20261022T213005Z"


def clock() -> datetime:
    return NOW


@pytest.fixture
def root(tmp_path: Path) -> Path:
    for role in ArmRole:
        (tmp_path / "hardware" / "calibration" / role.value).mkdir(parents=True)
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs" / "local.yaml").write_text(EXAMPLE.read_text())
    return tmp_path.resolve()


def target(root: Path, role: ArmRole = ArmRole.FOLLOWER) -> Path:
    return root / "hardware" / "calibration" / role.value / "main.json"


def install(root: Path, fixture: str, role: ArmRole = ArmRole.FOLLOWER) -> Path:
    path = target(root, role)
    shutil.copy(FIXTURES / fixture, path)
    return path


class FakeLeRobot:
    """Stands in for lerobot-calibrate: writes ``fixture`` to the target file."""

    def __init__(self, path: Path, fixture: str | None, code: int = 0) -> None:
        self.path = path
        self.fixture = fixture
        self.code = code
        self.calls: list[list[str]] = []
        self.saw_backup: list[Path] = []

    def __call__(self, argv: list[str]) -> int:
        self.calls.append(argv)
        self.saw_backup = sorted((self.path.parent / "backups").glob("*"))
        if self.fixture is not None:
            shutil.copy(FIXTURES / self.fixture, self.path)
        return self.code


def expected_argv(root: Path, role: ArmRole) -> list[str]:
    config = load_machine_config(root / "configs" / "local.yaml")
    return calibrate_argv(config, role, root)


def run(root: Path, runner: FakeLeRobot, *args: str) -> int:
    return main(list(args), runner=runner, root=root, now=clock)


def test_backup_path_is_outside_the_checked_json_glob(root: Path) -> None:
    path = backup_path(target(root), NOW)
    assert path == target(root).parent / "backups" / f"main.{STAMP}.json.bak"
    assert not path.match("*.json")


def test_dry_run_prints_the_plan_and_touches_nothing(root, capsys) -> None:
    old = install(root, "follower_main.json")
    before = old.read_bytes()
    runner = FakeLeRobot(old, "follower_recalibrated.json")
    assert run(root, runner, "--role", "follower", "--dry-run") == 0
    out = capsys.readouterr().out
    assert runner.calls == []
    assert old.read_bytes() == before
    assert not (old.parent / "backups").exists()
    assert str(old) in out
    assert str(backup_path(old, NOW)) in out
    assert format_command(expected_argv(root, ArmRole.FOLLOWER)) in out
    assert "type 'c'" in out
    assert "anything other than 'c' keeps the existing file" in out


def test_dry_run_on_first_calibration_says_no_backup(root, capsys) -> None:
    runner = FakeLeRobot(target(root, ArmRole.LEADER), "leader_main.json")
    assert run(root, runner, "--role", "leader", "--dry-run") == 0
    out = capsys.readouterr().out
    assert "none, first calibration" in out
    assert format_command(expected_argv(root, ArmRole.LEADER)) in out
    assert runner.calls == []
    assert not target(root, ArmRole.LEADER).exists()


def test_recalibration_backs_up_then_runs_then_prints_the_diff(root, capsys) -> None:
    old = install(root, "follower_main.json")
    before = old.read_bytes()
    runner = FakeLeRobot(old, "follower_recalibrated.json")
    assert run(root, runner, "--role", "follower") == 0
    backup = backup_path(old, NOW)
    assert runner.calls == [expected_argv(root, ArmRole.FOLLOWER)]
    assert runner.saw_backup == [backup]  # the backup exists before LeRobot runs
    assert backup.read_bytes() == before
    out = capsys.readouterr().out
    assert "elbow_flex  homing_offset  1207  1247    +40" in out
    assert "passed" in out
    assert str(backup) in out


def test_first_calibration_skips_backup_and_diff(root, capsys) -> None:
    path = target(root, ArmRole.LEADER)
    runner = FakeLeRobot(path, "leader_main.json")
    assert run(root, runner, "--role", "leader") == 0
    out = capsys.readouterr().out
    assert "first calibration" in out.lower()
    assert "no backup" in out and "no diff" in out
    assert not (path.parent / "backups").exists()
    assert path.is_file()


def test_failed_check_exits_1_and_says_how_to_restore(root, capsys) -> None:
    old = install(root, "follower_main.json")
    before = old.read_bytes()
    runner = FakeLeRobot(old, "gripper_span_fail.json")
    assert run(root, runner, "--role", "follower") == 1
    captured = capsys.readouterr()
    backup = backup_path(old, NOW)
    assert backup.read_bytes() == before
    # Not restored automatically: the bad file stays for the owner to look at.
    assert old.read_bytes() == (FIXTURES / "gripper_span_fail.json").read_bytes()
    assert "gripper_span" in captured.err
    assert f"cp {backup} {old}" in captured.err


def test_failed_check_on_first_calibration_has_nothing_to_restore(root, capsys) -> None:
    path = target(root)
    runner = FakeLeRobot(path, "gripper_span_fail.json")
    assert run(root, runner, "--role", "follower") == 1
    err = capsys.readouterr().err
    assert "no previous file" in err
    assert "cp " not in err


def test_keeping_the_existing_file_drops_the_identical_backup(root, capsys) -> None:
    # Pressing ENTER at LeRobot's prompt keeps the file: LeRobot writes nothing.
    old = install(root, "follower_main.json")
    runner = FakeLeRobot(old, None)
    assert run(root, runner, "--role", "follower") == 0
    out = capsys.readouterr().out
    assert "unchanged" in out
    assert not backup_path(old, NOW).exists()


def test_lerobot_failure_returns_its_code_and_names_the_backup(root, capsys) -> None:
    old = install(root, "follower_main.json")
    runner = FakeLeRobot(old, None, code=130)
    assert run(root, runner, "--role", "follower") == 130
    err = capsys.readouterr().err
    assert "exited with code 130" in err
    assert str(backup_path(old, NOW)) in err
    # The file may be truncated mid-save, so the restore command is printed.
    assert f"cp {backup_path(old, NOW)} {old}" in err


def test_no_file_after_a_clean_run_is_an_error(root, capsys) -> None:
    runner = FakeLeRobot(target(root), None)
    assert run(root, runner, "--role", "follower") == 1
    assert "no calibration file" in capsys.readouterr().err


def test_existing_backup_is_never_overwritten(root, capsys) -> None:
    old = install(root, "follower_main.json")
    backup = backup_path(old, NOW)
    backup.parent.mkdir()
    backup.write_text("earlier")
    runner = FakeLeRobot(old, "follower_recalibrated.json")
    assert run(root, runner, "--role", "follower") == 1
    assert backup.read_text() == "earlier"
    assert runner.calls == []


def test_config_flag_picks_another_machine_config(root, tmp_path, capsys) -> None:
    other = tmp_path / "other.yaml"
    other.write_text(EXAMPLE.read_text().replace("id: main ", "id: spare "))
    runner = FakeLeRobot(target(root), None)
    code = run(root, runner, "--role", "follower", "--dry-run", "--config", str(other))
    assert code == 0
    assert "follower/spare.json" in capsys.readouterr().out


def test_missing_local_config_is_an_error(root, capsys) -> None:
    (root / "configs" / "local.yaml").unlink()
    runner = FakeLeRobot(target(root), None)
    assert run(root, runner, "--role", "follower") == 1
    assert "so101-find-ports" in capsys.readouterr().err
    assert runner.calls == []


class InterruptedLeRobot(FakeLeRobot):
    def __call__(self, argv: list[str]) -> int:
        self.calls.append(argv)
        raise KeyboardInterrupt


def test_ctrl_c_during_the_run_exits_130_with_the_restore_command(root, capsys) -> None:
    old = install(root, "follower_main.json")
    runner = InterruptedLeRobot(old, None)
    assert run(root, runner, "--role", "follower") == 130
    err = capsys.readouterr().err
    backup = backup_path(old, NOW)
    assert f"backed up at {backup}" in err
    assert f"cp {backup} {old}" in err


def test_ctrl_c_on_first_calibration_exits_130(root, capsys) -> None:
    runner = InterruptedLeRobot(target(root), None)
    assert run(root, runner, "--role", "follower") == 130
    assert "interrupted" in capsys.readouterr().err


CORRUPT = ["{not json", "{}"]


@pytest.mark.parametrize("text", CORRUPT, ids=["bad-json", "no-joints"])
@pytest.mark.parametrize("dry", [False, True], ids=["run", "dry-run"])
def test_unreadable_previous_file_is_refused_before_lerobot(
    root, capsys, text: str, dry: bool
) -> None:
    # LeRobot itself crashes loading it (robots/robot.py L56) before asking.
    old = target(root)
    old.write_text(text)
    runner = FakeLeRobot(old, "follower_recalibrated.json")
    args = ["--role", "follower"] + (["--dry-run"] if dry else [])
    assert run(root, runner, *args) == 1
    err = capsys.readouterr().err
    assert runner.calls == []
    assert old.read_text() == text
    assert not (old.parent / "backups").exists()
    assert "unreadable" in err
    assert f"mkdir -p {old.parent / 'backups'}" in err
    assert f"mv {old} {backup_path(old, NOW)}" in err
    assert "--move-corrupt" in err


def test_move_corrupt_moves_the_file_aside_and_calibrates(root, capsys) -> None:
    old = target(root)
    old.write_text("{not json")
    runner = FakeLeRobot(old, "follower_recalibrated.json")
    assert run(root, runner, "--role", "follower", "--move-corrupt") == 0
    out = capsys.readouterr().out
    backup = backup_path(old, NOW)
    assert backup.read_text() == "{not json"
    assert runner.calls == [expected_argv(root, ArmRole.FOLLOWER)]
    assert runner.saw_backup == [backup]
    assert f"Moved the unreadable {old} to {backup}" in out
    assert "no diff" in out
    assert "Sanity checks passed" in out


def test_move_corrupt_dry_run_moves_nothing(root, capsys) -> None:
    old = target(root)
    old.write_text("{not json")
    runner = FakeLeRobot(old, None)
    assert run(root, runner, "--role", "follower", "--move-corrupt", "--dry-run") == 0
    out = capsys.readouterr().out
    assert f"would move the unreadable file to {backup_path(old, NOW)}" in out
    assert old.read_text() == "{not json"
    assert not (old.parent / "backups").exists()
    assert runner.calls == []


def test_move_corrupt_with_a_readable_file_is_a_normal_run(root, capsys) -> None:
    old = install(root, "follower_main.json")
    runner = FakeLeRobot(old, "follower_recalibrated.json")
    assert run(root, runner, "--role", "follower", "--move-corrupt") == 0
    out = capsys.readouterr().out
    assert "Changes per joint:" in out
    assert backup_path(old, NOW).is_file()
