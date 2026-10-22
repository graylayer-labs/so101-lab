from pathlib import Path

import pytest
import yaml

from hw_setup.find_ports import FindPortsError, find_ports, main
from so101 import ArmRole, load_machine_config

REPO = Path(__file__).resolve().parents[3]
EXAMPLE = REPO / "configs" / "example.yaml"
LEADER = "/dev/cu.usbmodem111"
FOLLOWER = "/dev/cu.usbmodem222"
OTHER = "/dev/cu.Bluetooth-Incoming-Port"


class FakeBoard:
    """Stands in for the USB bus: the lister reads it, input() mutates it.

    ``script`` is one action per prompt: the port to unplug, or None to replug
    whatever was last unplugged.
    """

    def __init__(self, script: list[str | None], present: set[str] | None = None):
        self.present = present or {LEADER, FOLLOWER, OTHER}
        self.script = list(script)
        self.unplugged: str | None = None
        self.prompts: list[str] = []

    def lister(self) -> list[str]:
        return sorted(self.present)

    def input(self, prompt: str = "") -> str:
        self.prompts.append(prompt)
        if not self.script:
            return ""  # owner pressed Enter without touching the cable
        action = self.script.pop(0)
        if action is None:
            assert self.unplugged
            self.present.add(self.unplugged)
        else:
            self.present.discard(action)
            self.unplugged = action
        return ""


def _board(order=(LEADER, FOLLOWER)) -> FakeBoard:
    script: list[str | None] = []
    for port in order:
        script += [port, None]
    return FakeBoard(script)


def test_find_ports_diffs_the_lists_for_each_arm():
    board = _board()
    ports = find_ports(board.lister, board.input, sleep=lambda _s: None)
    assert ports == {ArmRole.LEADER: LEADER, ArmRole.FOLLOWER: FOLLOWER}
    assert len(board.prompts) == 4
    assert "leader" in board.prompts[0] and "follower" in board.prompts[2]


def test_no_change_after_unplug_is_an_error():
    board = _board()

    def lazy_input(prompt: str = "") -> str:
        return ""  # the owner pressed Enter without unplugging

    with pytest.raises(FindPortsError, match="leader.*no port"):
        find_ports(board.lister, lazy_input, sleep=lambda _s: None)


def test_two_ports_disappearing_is_an_error():
    present = {LEADER, FOLLOWER}

    def lister() -> list[str]:
        return sorted(present)

    def inp(prompt: str = "") -> str:
        present.clear()
        return ""

    with pytest.raises(FindPortsError, match="more than one"):
        find_ports(lister, inp, sleep=lambda _s: None)


def test_port_that_does_not_return_is_an_error():
    board = FakeBoard([LEADER])  # unplugged, never replugged
    with pytest.raises(FindPortsError, match="did not come back"):
        find_ports(board.lister, board.input, sleep=lambda _s: None)


def _local(tmp_path: Path) -> Path:
    path = tmp_path / "local.yaml"
    data = yaml.safe_load(EXAMPLE.read_text())
    data["cameras"]["front"]["fps"] = 15
    path.write_text(yaml.safe_dump(data))
    return path


def test_main_writes_ports_keeps_other_keys_and_validates(tmp_path):
    board = _board()
    config = _local(tmp_path)
    code = main(
        ["--config", str(config)],
        lister=board.lister,
        input_fn=board.input,
        sleep=lambda _s: None,
    )
    assert code == 0
    loaded = load_machine_config(config)
    assert loaded.arms[ArmRole.LEADER].port == LEADER
    assert loaded.arms[ArmRole.FOLLOWER].port == FOLLOWER
    assert loaded.cameras["front"].fps == 15  # untouched
    assert loaded.arms[ArmRole.LEADER].arm_id == "main"


def test_main_creates_local_yaml_from_the_example(tmp_path):
    board = _board()
    config = tmp_path / "local.yaml"
    main(
        ["--config", str(config), "--example", str(EXAMPLE)],
        lister=board.lister,
        input_fn=board.input,
        sleep=lambda _s: None,
    )
    assert load_machine_config(config).arms[ArmRole.FOLLOWER].port == FOLLOWER


def test_missing_config_without_example_is_an_error(tmp_path, capsys):
    board = _board()
    code = main(
        ["--config", str(tmp_path / "local.yaml"), "--example", str(tmp_path / "x")],
        lister=board.lister,
        input_fn=board.input,
        sleep=lambda _s: None,
    )
    assert code == 1
    assert "not found" in capsys.readouterr().err


def test_dry_run_prints_plan_and_touches_nothing(tmp_path, capsys):
    config = _local(tmp_path)
    before = config.read_text()

    def boom(*_a, **_k):
        raise AssertionError("dry run must not list ports or read input")

    code = main(["--dry-run", "--config", str(config)], lister=boom, input_fn=boom)
    out = capsys.readouterr().out
    assert code == 0
    assert config.read_text() == before
    assert list(tmp_path.iterdir()) == [config]
    assert "dry run" in out.lower()
    assert str(config) in out
    assert "arms.leader.port" in out and "arms.follower.port" in out
    assert "list_ports" in out


def test_dry_run_with_missing_config_says_it_would_create_it(tmp_path, capsys):
    config = tmp_path / "local.yaml"
    main(["--dry-run", "--config", str(config), "--example", str(EXAMPLE)])
    assert "create" in capsys.readouterr().out
    assert not config.exists()


def test_invalid_result_is_not_written(tmp_path, capsys):
    config = _local(tmp_path)
    before = config.read_text()
    bad = {LEADER, "not-a-port"}
    board = FakeBoard(["not-a-port", None, LEADER, None], present=bad)
    code = main(
        ["--config", str(config)],
        lister=board.lister,
        input_fn=board.input,
        sleep=lambda _s: None,
    )
    assert code == 1
    assert config.read_text() == before
    assert "arms.leader.port" in capsys.readouterr().err
