"""Tests for so101-setup-motors. No hardware: the runner and input are fakes."""

from collections.abc import Callable
from pathlib import Path

import pytest

from hw_setup.lerobot_argv import format_command, setup_motors_argv
from hw_setup.setup_motors import GEAR_RATIOS, main
from so101.arm import ArmRole
from so101.machine_config import load_machine_config

EXAMPLE = Path(__file__).parents[3] / "configs" / "example.yaml"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / "hardware" / "calibration").mkdir(parents=True)
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs" / "local.yaml").write_text(EXAMPLE.read_text())
    return tmp_path


class Runner:
    def __init__(self, code: int = 0) -> None:
        self.calls: list[list[str]] = []
        self.code = code

    def __call__(self, argv: list[str]) -> int:
        self.calls.append(argv)
        return self.code


def answers(*replies: str) -> Callable[[str], str]:
    queue = list(replies)

    def fake(prompt: str = "") -> str:
        return queue.pop(0)

    return fake


def expected(root: Path, role: ArmRole) -> list[str]:
    config = load_machine_config(root / "configs" / "local.yaml")
    return setup_motors_argv(config, role, root.resolve())


def test_gear_ratios_match_the_bom() -> None:
    assert GEAR_RATIOS[ArmRole.LEADER] == (191, 345, 191, 147, 147, 147)
    assert GEAR_RATIOS[ArmRole.FOLLOWER] == (345,) * 6


@pytest.mark.parametrize("role", ["leader", "follower"])
def test_confirmed_run_calls_runner_with_the_argv(root: Path, role: str) -> None:
    runner = Runner()
    code = main(["--role", role], runner=runner, input_fn=answers("y"), root=root)
    assert code == 0
    assert runner.calls == [expected(root, ArmRole(role))]


def test_runner_exit_code_is_returned(root: Path) -> None:
    code = main(
        ["--role", "leader"], runner=Runner(3), input_fn=answers("y"), root=root
    )
    assert code == 3


@pytest.mark.parametrize("reply", ["", "n", "no", "maybe"])
def test_anything_but_yes_aborts(root: Path, reply: str) -> None:
    runner = Runner()
    code = main(["--role", "leader"], runner=runner, input_fn=answers(reply), root=root)
    assert code == 1
    assert runner.calls == []


def test_eof_at_the_prompt_aborts(root: Path) -> None:
    def eof(prompt: str = "") -> str:
        raise EOFError

    runner = Runner()
    assert main(["--role", "leader"], runner=runner, input_fn=eof, root=root) == 1
    assert runner.calls == []


def test_leader_info_is_printed_before_the_prompt(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: list[str] = []

    def spy(prompt: str = "") -> str:
        seen.append(capsys.readouterr().out)
        return "y"

    main(["--role", "leader"], runner=Runner(), input_fn=spy, root=root)
    out = seen[0]
    assert out.index("gripper") < out.index("shoulder_pan")
    for line in (
        "1 shoulder_pan: 1/191",
        "2 shoulder_lift: 1/345",
        "3 elbow_flex: 1/191",
        "4 wrist_flex: 1/147",
        "5 wrist_roll: 1/147",
        "6 gripper: 1/147",
    ):
        assert line in out
    assert "5 V" in out


def test_follower_info(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["--role", "follower"], runner=Runner(), input_fn=answers("y"), root=root)
    out = capsys.readouterr().out
    assert out.count("1/345") == 6
    assert "1/191" not in out
    assert "12 V" in out and "5 V" in out


def test_leader_power_warning_never_mentions_12v(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["--role", "leader"], runner=Runner(), input_fn=answers("y"), root=root)
    out = capsys.readouterr().out
    assert "always uses 5 V" in out
    assert "12 V" not in out


def test_dry_run_prints_command_and_runs_nothing(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = Runner()

    def no_input(prompt: str = "") -> str:
        raise AssertionError("dry run must not ask")

    code = main(
        ["--role", "follower", "--dry-run"],
        runner=runner,
        input_fn=no_input,
        root=root,
    )
    out = capsys.readouterr().out
    assert code == 0
    assert runner.calls == []
    assert format_command(expected(root, ArmRole.FOLLOWER)) in out
    assert "1/345" in out and "gripper" in out


def test_explicit_config_path(
    root: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    other = tmp_path_factory.mktemp("cfg") / "mine.yaml"
    other.write_text(EXAMPLE.read_text().replace("usbmodem0000000001", "usbmodemZZZ"))
    runner = Runner()
    main(
        ["--role", "leader", "--config", str(other)],
        runner=runner,
        input_fn=answers("y"),
        root=root,
    )
    assert "--teleop.port=/dev/cu.usbmodemZZZ" in runner.calls[0]


def test_missing_config_fails_with_a_hint(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (root / "configs" / "local.yaml").unlink()
    runner = Runner()
    code = main(["--role", "leader"], runner=runner, input_fn=answers("y"), root=root)
    err = capsys.readouterr().err
    assert code == 1
    assert "so101-find-ports" in err and "example.yaml" in err
    assert runner.calls == []


def test_role_is_required_and_validated(root: Path) -> None:
    with pytest.raises(SystemExit) as err:
        main([], runner=Runner(), input_fn=answers(), root=root)
    assert err.value.code == 2
    with pytest.raises(SystemExit):
        main(["--role", "both"], runner=Runner(), input_fn=answers(), root=root)
