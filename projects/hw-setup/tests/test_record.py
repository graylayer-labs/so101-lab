"""Tests for so101-record. Tmp workspaces and dataset folders; no hardware."""

import json
import re
import shutil
from pathlib import Path

import datasets
import pandas as pd
import pytest
from lerobot.datasets.dataset_metadata import CODEBASE_VERSION, LeRobotDatasetMetadata
from lerobot.datasets.feature_utils import create_empty_dataset_info
from lerobot.datasets.io_utils import write_episodes, write_info, write_tasks
from lerobot.utils.constants import DEFAULT_FEATURES

from hw_setup.lerobot_argv import format_command, record_argv
from hw_setup.record import main, missing_metadata
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
        "max_relative_target": 5.0,
        **kwargs,
    }
    return record_argv(config, root.resolve(), **options)


def make_dataset(path: Path, episodes: int = 1) -> Path:
    """Real LeRobot v3.0 metadata, written with LeRobot's own writers."""
    path.mkdir(parents=True)
    info = create_empty_dataset_info(
        CODEBASE_VERSION, 30, dict(DEFAULT_FEATURES), False, "so_follower"
    )
    info.total_episodes = episodes
    info.total_tasks = 1 if episodes else 0
    write_info(info, path)
    if episodes:
        write_tasks(pd.DataFrame({"task_index": [0]}, index=pd.Index(["Pick"])), path)
        rows = {"episode_index": list(range(episodes))}
        write_episodes(datasets.Dataset.from_dict(rows), path)
    return path


def lerobot_falls_back_to_the_hub(path: Path) -> bool:
    """Whether LeRobot's _load_metadata raises the errors that make it pull
    meta/ from the Hub (datasets/dataset_metadata.py L134-148). It only reads
    local files: no network."""
    meta = LeRobotDatasetMetadata.__new__(LeRobotDatasetMetadata)
    meta.repo_id, meta.root, meta._requested_root = "me/cube", path, path
    try:
        meta._load_metadata()
    except (FileNotFoundError, NotADirectoryError):
        return True
    return False


def break_dataset(path: Path, part: str) -> None:
    if part == "info":
        (path / "meta" / "info.json").unlink()
    elif part == "tasks":
        (path / "meta" / "tasks.parquet").unlink()
    elif part == "episodes":
        shutil.rmtree(path / "meta" / "episodes")
    elif part == "episodes-empty":
        shutil.rmtree(path / "meta" / "episodes")
        (path / "meta" / "episodes" / "chunk-000").mkdir(parents=True)
    elif part == "meta-is-a-file":
        shutil.rmtree(path / "meta")
        (path / "meta").write_text("")


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


PARTS = ["info", "tasks", "episodes", "episodes-empty", "meta-is-a-file"]


@pytest.mark.parametrize("part", [None, *PARTS])
def test_metadata_check_mirrors_lerobots_hub_fallback(
    home: Path, part: str | None
) -> None:
    target = make_dataset(home / "me" / "cube")
    if part:
        break_dataset(target, part)
    assert bool(missing_metadata(target)) == lerobot_falls_back_to_the_hub(target)
    assert bool(part) == lerobot_falls_back_to_the_hub(target)


def test_a_dataset_with_no_episodes_yet_is_complete(home: Path) -> None:
    # What a crash during the first episode leaves: info.json only.
    target = make_dataset(home / "me" / "cube", episodes=0)
    assert missing_metadata(target) == []
    assert not lerobot_falls_back_to_the_hub(target)


def test_unreadable_info_counts_as_incomplete(home: Path) -> None:
    target = make_dataset(home / "me" / "cube")
    (target / "meta" / "info.json").write_text("{not json")
    assert missing_metadata(target) != []


@pytest.mark.parametrize("resume", [False, True])
@pytest.mark.parametrize("part", PARTS)
def test_incomplete_dataset_names_the_state_and_how_to_set_it_aside(
    root: Path,
    home: Path,
    part: str,
    resume: bool,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = make_dataset(home / "me" / "cube")
    break_dataset(target, part)
    runner = Runner()
    args = [*BASE, "--resume"] if resume else BASE
    assert run(args, root, home, runner) == 1
    assert runner.calls == []
    err = capsys.readouterr().err
    assert "incomplete dataset" in err
    resolved = re.escape(str(target.resolve()))
    assert re.search(rf"mv {resolved} {resolved}\.broken-\d{{8}}-\d{{6}}", err)
    assert "Drop --resume" not in err and "Pass --resume" not in err
    assert target.exists()


def test_empty_folder_is_an_incomplete_dataset(
    root: Path, home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (home / "me" / "cube").mkdir(parents=True)
    assert run([*BASE, "--resume"], root, home) == 1
    assert "incomplete dataset" in capsys.readouterr().err


@pytest.mark.parametrize("dry", [[], ["--dry-run"]])
def test_eval_names_are_refused_for_a_new_dataset(
    root: Path, home: Path, dry: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    args = ["--task", "T", "--repo-id", "me/eval_cube", "--episodes", "1", *dry]
    runner = Runner()
    with pytest.raises(SystemExit) as err:
        run(args, root, home, runner)
    assert err.value.code == 2
    assert runner.calls == []
    assert "eval_" in capsys.readouterr().err


def test_eval_names_can_be_resumed(root: Path, home: Path) -> None:
    # LeRobot checks the prefix only when it creates a dataset.
    make_dataset(home / "me" / "eval_cube")
    args = ["--task", "T", "--repo-id", "me/eval_cube", "--episodes", "1"]
    runner = Runner()
    assert run([*args, "--resume"], root, home, runner) == 0
    assert len(runner.calls) == 1


def test_eval_only_matters_in_the_name_part(root: Path, home: Path) -> None:
    runner = Runner()
    args = ["--task", "T", "--repo-id", "eval_me/cube", "--episodes", "1"]
    assert run(args, root, home, runner) == 0


def test_resume_on_an_existing_dataset(root: Path, home: Path) -> None:
    target = make_dataset(home / "me" / "cube")
    runner = Runner()
    assert run([*BASE, "--resume"], root, home, runner) == 0
    assert runner.calls == [expected(root, target.resolve(), resume=True)]


def test_resume_without_a_local_dataset_is_refused(
    root: Path, home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # LeRobot would fall back to downloading meta/ from the Hub.
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
    assert "--teleop.port=/dev/cu.usbmodemZZZ" in runner.calls[0]


def test_missing_config_fails_with_a_hint(
    root: Path, home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (root / "configs" / "local.yaml").unlink()
    runner = Runner()
    assert run(BASE, root, home, runner) == 1
    assert runner.calls == []
    assert "so101-find-ports" in capsys.readouterr().err


def test_default_lerobot_home_is_lerobots_own(
    root: Path, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # HF_LEROBOT_HOME is read from the environment when lerobot.utils.constants
    # is first imported (L69), so the module attribute is what to patch.
    import lerobot.utils.constants

    monkeypatch.setattr(lerobot.utils.constants, "HF_LEROBOT_HOME", home)
    runner = Runner()
    assert main(BASE, runner=runner, root=root) == 0
    assert f"--dataset.root={home.resolve() / 'me' / 'cube'}" in runner.calls[0]


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


# --- movement cap (#63) ----------------------------------------------------


def test_default_cap_is_passed(root: Path, home: Path) -> None:
    runner = Runner()
    run(BASE, root, home, runner)
    assert "--robot.max_relative_target=5.0" in runner.calls[0]


def test_max_step_sets_the_cap(root: Path, home: Path) -> None:
    runner = Runner()
    run([*BASE, "--max-step", "3"], root, home, runner)
    assert runner.calls == [
        expected(root, home / "me" / "cube", max_relative_target=3.0)
    ]


def test_max_step_none_removes_the_cap_with_a_warning(
    root: Path, home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = Runner()
    assert run([*BASE, "--max-step", "none"], root, home, runner) == 0
    assert "--robot.max_relative_target=null" in runner.calls[0]
    assert "no movement cap" in capsys.readouterr().err


@pytest.mark.parametrize("bad", ["0", "-2", "x"])
def test_max_step_that_is_not_positive_is_refused(
    root: Path, home: Path, bad: str
) -> None:
    runner = Runner()
    with pytest.raises(SystemExit) as exit_info:
        run([*BASE, "--max-step", bad], root, home, runner)
    assert exit_info.value.code == 2
    assert runner.calls == []
