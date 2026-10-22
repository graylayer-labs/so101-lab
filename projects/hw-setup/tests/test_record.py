"""Tests for so101-record. Tmp workspaces and dataset folders; no hardware."""

import json
import shutil
from pathlib import Path

import pytest

from hw_setup.lerobot_argv import format_command, record_argv
from hw_setup.record import main
from so101.machine_config import load_machine_config

REPO = Path(__file__).parents[3]
EXAMPLE = REPO / "configs" / "example.yaml"
ARMS = ("leader", "follower")
BASE = ["--task", "Pick up the red cube", "--repo-id", "me/cube", "--episodes", "3"]


@pytest.fixture
def root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    workspace = tmp_path_factory.mktemp("workspace")
    for arm in ARMS:
        target = workspace / "hardware" / "calibration" / arm
        target.mkdir(parents=True)
        shutil.copy(REPO / "hardware" / "calibration" / arm / "main.json", target)
    (workspace / "configs").mkdir()
    (workspace / "configs" / "local.yaml").write_text(EXAMPLE.read_text())
    return workspace


@pytest.fixture
def home(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Stands in for $HF_LEROBOT_HOME, outside the workspace."""
    return tmp_path_factory.mktemp("lerobot-home")


class Runner:
    def __init__(self, code: int = 0) -> None:
        self.calls: list[list[str]] = []
        self.code = code

    def __call__(self, argv: list[str]) -> int:
        self.calls.append(argv)
        return self.code


def run(args: list[str], root: Path, home: Path, runner: Runner | None = None) -> int:
    return main(args, runner=runner or Runner(), root=root, lerobot_home=home)


def expected(root: Path, dataset_root: Path, **kwargs: object) -> list[str]:
    config = load_machine_config(root / "configs" / "local.yaml")
    options: dict = {
        "repo_id": "me/cube",
        "single_task": "Pick up the red cube",
        "num_episodes": 3,
        "dataset_root": dataset_root,
        "push_to_hub": False,
        "no_stamp": True,
        **kwargs,
    }
    return record_argv(config, root.resolve(), **options)


def make_dataset(path: Path) -> Path:
    (path / "meta").mkdir(parents=True)
    (path / "meta" / "info.json").write_text("{}")
    return path


def test_default_run(root: Path, home: Path) -> None:
    runner = Runner()
    assert run(BASE, root, home, runner) == 0
    assert runner.calls == [expected(root, home.resolve() / "me" / "cube")]


def test_push_to_hub_is_always_false(root: Path, home: Path) -> None:
    runner = Runner()
    run(BASE, root, home, runner)
    assert "--dataset.push_to_hub=false" in runner.calls[0]
    assert sum("push_to_hub" in arg for arg in runner.calls[0]) == 1


def test_there_is_no_flag_to_push(root: Path, home: Path) -> None:
    with pytest.raises(SystemExit) as err:
        run([*BASE, "--push-to-hub"], root, home)
    assert err.value.code == 2


def test_runner_exit_code_is_returned(root: Path, home: Path) -> None:
    assert run(BASE, root, home, Runner(5)) == 5


def test_all_options_reach_the_argv(
    root: Path, home: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    target = tmp_path_factory.mktemp("data") / "cube"
    runner = Runner()
    args = [
        *BASE,
        "--dataset-root",
        str(target),
        "--episode-time-s",
        "20",
        "--reset-time-s",
        "5.5",
        "--fps",
        "15",
        "--no-cameras",
        "--display",
    ]
    assert run(args, root, home, runner) == 0
    assert runner.calls == [
        expected(
            root,
            target.resolve(),
            episode_time_s=20.0,
            reset_time_s=5.5,
            fps=15,
            cameras=False,
            display_data=True,
        )
    ]


@pytest.mark.parametrize("task", ["", "   ", "\t\n"])
def test_task_text_is_required(root: Path, home: Path, task: str) -> None:
    args = ["--task", task, "--repo-id", "me/cube", "--episodes", "3"]
    with pytest.raises(SystemExit) as err:
        run(args, root, home)
    assert err.value.code == 2


def test_task_flag_is_required(root: Path, home: Path) -> None:
    with pytest.raises(SystemExit) as err:
        run(["--repo-id", "me/cube", "--episodes", "3"], root, home)
    assert err.value.code == 2


@pytest.mark.parametrize("repo_id", ["cube", "me/", "/cube", "a/b/c", "me/my cube"])
def test_repo_id_must_be_user_slash_name(root: Path, home: Path, repo_id: str) -> None:
    args = ["--task", "T", "--repo-id", repo_id, "--episodes", "3"]
    with pytest.raises(SystemExit) as err:
        run(args, root, home)
    assert err.value.code == 2


@pytest.mark.parametrize("episodes", ["0", "-1", "two"])
def test_episodes_must_be_positive(root: Path, home: Path, episodes: str) -> None:
    args = ["--task", "T", "--repo-id", "me/cube", "--episodes", episodes]
    with pytest.raises(SystemExit) as err:
        run(args, root, home)
    assert err.value.code == 2


@pytest.mark.parametrize(
    "inside", ["data/cube", ".", "projects/hw-setup/../../data", "hardware"]
)
def test_dataset_root_inside_the_workspace_is_refused(
    root: Path, home: Path, inside: str, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = Runner()
    code = run([*BASE, "--dataset-root", str(root / inside)], root, home, runner)
    assert code == 1
    assert runner.calls == []
    assert "inside the workspace" in capsys.readouterr().err


def test_relative_dataset_root_is_resolved_from_the_cwd(
    root: Path, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(root / "configs")
    runner = Runner()
    assert run([*BASE, "--dataset-root", "../out"], root, home, runner) == 1
    assert runner.calls == []


def test_symlink_into_the_workspace_is_refused(
    root: Path, home: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    link = tmp_path_factory.mktemp("links") / "data"
    link.symlink_to(root, target_is_directory=True)
    runner = Runner()
    assert run([*BASE, "--dataset-root", str(link / "cube")], root, home, runner) == 1
    assert runner.calls == []


def test_lerobot_home_inside_the_workspace_is_refused(root: Path) -> None:
    runner = Runner()
    assert run(BASE, root, root / "cache", runner) == 1
    assert runner.calls == []


def test_default_dataset_root_is_printed(
    root: Path, home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run(BASE, root, home)
    assert f"Dataset root: {home.resolve() / 'me' / 'cube'}" in capsys.readouterr().out


def test_existing_root_without_resume_is_refused(
    root: Path, home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    make_dataset(home / "me" / "cube")
    runner = Runner()
    assert run(BASE, root, home, runner) == 1
    assert runner.calls == []
    err = capsys.readouterr().err
    assert "already exists" in err and "--resume" in err


def test_existing_empty_folder_without_resume_is_refused(
    root: Path, home: Path
) -> None:
    # LeRobot's create() makes the root with exist_ok=False: any folder fails.
    (home / "me" / "cube").mkdir(parents=True)
    runner = Runner()
    assert run(BASE, root, home, runner) == 1
    assert runner.calls == []


def test_resume_on_an_existing_dataset(root: Path, home: Path) -> None:
    target = make_dataset(home / "me" / "cube")
    runner = Runner()
    assert run([*BASE, "--resume"], root, home, runner) == 0
    assert runner.calls == [expected(root, target.resolve(), resume=True)]


@pytest.mark.parametrize("make", [False, True])
def test_resume_without_a_local_dataset_is_refused(
    root: Path, home: Path, make: bool, capsys: pytest.CaptureFixture[str]
) -> None:
    # LeRobot would fall back to downloading meta/ from the Hub.
    if make:
        (home / "me" / "cube").mkdir(parents=True)
    runner = Runner()
    assert run([*BASE, "--resume"], root, home, runner) == 1
    assert runner.calls == []
    assert "nothing to resume" in capsys.readouterr().err


def test_dry_run_prints_the_plan_and_runs_nothing(
    root: Path, home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = Runner()
    assert run([*BASE, "--dry-run"], root, home, runner) == 0
    assert runner.calls == []
    out = capsys.readouterr().out
    target = home.resolve() / "me" / "cube"
    assert format_command(expected(root, target)) in out
    assert "Task: Pick up the red cube" in out
    assert "Episodes: 3" in out
    assert "Push to Hub: no" in out
    assert "new dataset" in out
    assert not target.exists()


def test_dry_run_resume_names_the_mode(
    root: Path, home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    make_dataset(home / "me" / "cube")
    assert run([*BASE, "--resume", "--dry-run"], root, home) == 0
    assert "resume" in capsys.readouterr().out


def test_bad_calibration_refuses_even_in_dry_run(
    root: Path, home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = root / "hardware" / "calibration" / "follower" / "main.json"
    data = json.loads(path.read_text())
    data.pop("gripper")
    path.write_text(json.dumps(data))
    runner = Runner()
    assert run([*BASE, "--dry-run"], root, home, runner) == 1
    assert runner.calls == []
    err = capsys.readouterr().err
    assert "refusing to run" in err and "follower" in err


def test_missing_calibration_refuses(root: Path, home: Path) -> None:
    (root / "hardware" / "calibration" / "leader" / "main.json").unlink()
    runner = Runner()
    assert run(BASE, root, home, runner) == 1
    assert runner.calls == []


def test_explicit_config_path(
    root: Path, home: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    other = tmp_path_factory.mktemp("cfg") / "mine.yaml"
    other.write_text(EXAMPLE.read_text().replace("usbmodem0000000001", "usbmodemZZZ"))
    runner = Runner()
    run([*BASE, "--config", str(other)], root, home, runner)
    assert "--teleop.port=/dev/tty.usbmodemZZZ" in runner.calls[0]


def test_missing_config_fails_with_a_hint(
    root: Path, home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (root / "configs" / "local.yaml").unlink()
    runner = Runner()
    assert run(BASE, root, home, runner) == 1
    assert runner.calls == []
    assert "so101-find-ports" in capsys.readouterr().err


def test_default_lerobot_home_is_lerobots_own(root: Path) -> None:
    from lerobot.utils.constants import HF_LEROBOT_HOME

    runner = Runner()
    target = HF_LEROBOT_HOME.resolve() / "me" / "cube"
    if target.exists():
        pytest.skip(f"{target} exists on this machine")
    assert main(BASE, runner=runner, root=root) == 0
    assert f"--dataset.root={target}" in runner.calls[0]


def test_lerobot_parses_the_resume_command(root: Path, home: Path) -> None:
    import draccus
    from lerobot.scripts.lerobot_record import RecordConfig

    target = make_dataset(home / "me" / "cube")
    runner = Runner()
    run([*BASE, "--resume"], root, home, runner)
    cfg = draccus.parse(config_class=RecordConfig, args=runner.calls[0][1:])
    assert cfg.resume is True
    assert cfg.dataset.push_to_hub is False
    assert cfg.dataset.no_stamp is True
    assert cfg.dataset.root is not None
    assert Path(cfg.dataset.root) == target.resolve()
    assert cfg.dataset.single_task == "Pick up the red cube"
