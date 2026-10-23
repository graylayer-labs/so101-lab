"""Tests for so101-calibrate. No hardware: the runner is a fake that writes a file."""

import errno
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from hw_setup.calibrate import backup_path, copy_new, main, move_new
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
    assert "keeps the existing file" not in out
    assert "anything other than 'c' writes the stored calibration file" in out
    assert "to the motors" in out


def test_help_says_enter_writes_the_stored_file_to_the_motors(capsys) -> None:
    with pytest.raises(SystemExit):
        main(["--help"])
    out = " ".join(capsys.readouterr().out.split())
    assert "anything other than 'c' writes the stored calibration file" in out
    assert "to the motors" in out
    assert "so_follower.py L116-124" in out
    assert "keeps the existing file" not in out


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


GOOD_JOINT = '"id": 6, "drive_mode": 0, "homing_offset": 1'
# (file text, whether LeRobot's own loader crashes on it). Checked against
# draccus.load(dict[str, MotorCalibration]) as in robots/robot.py L159-160.
CORRUPT = {
    "bad-json": ("{not json", True),
    "not-motor-entries": ('{"gripper": 3}', True),
    "missing-motor-key": ('{"gripper": {' + GOOD_JOINT + ', "range_min": 1}}', True),
    "no-joints": ("{}", False),
    "range-inverted": (
        '{"gripper": {' + GOOD_JOINT + ', "range_min": 9, "range_max": 5}}',
        False,
    ),
}


@pytest.mark.parametrize("case", CORRUPT.values(), ids=CORRUPT.keys())
@pytest.mark.parametrize("dry", [False, True], ids=["run", "dry-run"])
def test_unusable_previous_file_is_refused_before_lerobot(
    root, capsys, case: tuple[str, bool], dry: bool
) -> None:
    text, lerobot_crashes = case
    old = target(root)
    old.write_text(text)
    runner = FakeLeRobot(old, "follower_recalibrated.json")
    args = ["--role", "follower"] + (["--dry-run"] if dry else [])
    assert run(root, runner, *args) == 1
    err = capsys.readouterr().err
    assert runner.calls == []
    assert old.read_text() == text
    assert not (old.parent / "backups").exists()
    assert f"mkdir -p {old.parent / 'backups'}" in err
    assert f"mv {old} {backup_path(old, NOW)}" in err
    assert "--move-corrupt" in err
    assert ("LeRobot would crash loading it" in err) is lerobot_crashes
    assert ("fails the sanity checks" in err) is not lerobot_crashes


def test_unreadable_permissions_are_refused_without_a_traceback(root, capsys) -> None:
    old = install(root, "follower_main.json")
    old.chmod(0)
    try:
        runner = FakeLeRobot(old, None)
        assert run(root, runner, "--role", "follower") == 1
    finally:
        old.chmod(0o644)
    err = capsys.readouterr().err
    assert "unreadable" in err and "LeRobot would crash" in err
    assert runner.calls == []


def test_a_directory_in_place_of_the_file_is_refused(root, capsys) -> None:
    old = target(root)
    old.mkdir()
    runner = FakeLeRobot(old, None)
    assert run(root, runner, "--role", "follower") == 1
    err = capsys.readouterr().err
    assert "unreadable" in err
    assert runner.calls == []


def test_a_directory_gets_its_own_reason_not_the_crash_one(root, capsys) -> None:
    # LeRobot skips a directory (robots/robot.py L55 checks is_file()), so it
    # calibrates, writes the motors, then fails to save.
    old = target(root)
    old.mkdir()
    runner = FakeLeRobot(old, None)
    assert run(root, runner, "--role", "follower") == 1
    err = capsys.readouterr().err
    assert "LeRobot would calibrate, write the motors, then fail to save" in err
    assert "would crash" not in err
    assert "--move-corrupt" in err


def test_move_corrupt_that_cannot_move_is_an_error(root, capsys) -> None:
    old = target(root)
    old.mkdir()  # hard links to a directory are not allowed
    runner = FakeLeRobot(old, None)
    assert run(root, runner, "--role", "follower", "--move-corrupt") == 1
    assert "cannot move" in capsys.readouterr().err
    assert runner.calls == []
    assert old.is_dir()


def test_copy_new_never_overwrites(tmp_path: Path) -> None:
    src, dst = tmp_path / "a", tmp_path / "b"
    src.write_text("new")
    dst.write_text("earlier")
    with pytest.raises(FileExistsError):
        copy_new(src, dst)
    assert dst.read_text() == "earlier"


class _FailingClose:
    """A file whose close() fails after closing, like a flush error at ENOSPC."""

    def __init__(self, real) -> None:
        self._real = real

    def __getattr__(self, name: str):
        return getattr(self._real, name)

    def __enter__(self):
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def close(self) -> None:
        self._real.close()
        raise OSError(errno.ENOSPC, "No space left on device")


def test_copy_new_removes_the_partial_file_when_close_fails(
    tmp_path: Path, monkeypatch
) -> None:
    src, dst = tmp_path / "a", tmp_path / "b"
    src.write_text("new")
    real_open = Path.open

    def fake_open(self: Path, mode: str = "r", *args, **kwargs):
        handle = real_open(self, mode, *args, **kwargs)
        return _FailingClose(handle) if mode == "xb" else handle

    monkeypatch.setattr(Path, "open", fake_open)
    with pytest.raises(OSError, match="No space"):
        copy_new(src, dst)
    assert not dst.exists()


def test_move_new_never_overwrites(tmp_path: Path) -> None:
    src, dst = tmp_path / "a", tmp_path / "b"
    src.write_text("new")
    dst.write_text("earlier")
    with pytest.raises(FileExistsError):
        move_new(src, dst)
    assert dst.read_text() == "earlier"
    assert src.read_text() == "new"


def test_copy_and_move_new_write_the_file(tmp_path: Path) -> None:
    src = tmp_path / "a"
    src.write_text("data")
    copy_new(src, tmp_path / "copy")
    move_new(src, tmp_path / "moved")
    assert (tmp_path / "copy").read_text() == "data"
    assert (tmp_path / "moved").read_text() == "data"
    assert not src.exists()


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
