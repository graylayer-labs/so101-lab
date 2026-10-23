"""The pre-flight checks on a checkpoint and its training dataset."""

import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from act_policy.policy_check import (
    PolicyError,
    camera_problems,
    load_policy,
    run_name,
    select_device,
)
from so101.machine_config import load_machine_config

REPO = Path(__file__).parents[3]
CONFIG = load_machine_config(REPO / "configs" / "example.yaml")
CAMERAS = {"front": (480, 640), "wrist": (480, 640)}  # as in conftest.py
MakePolicy = Callable[..., Path]


def test_a_saved_checkpoint_loads(make_policy: MakePolicy) -> None:
    policy = load_policy(make_policy())
    assert policy.policy_type == "act"
    assert policy.cameras == CAMERAS
    assert policy.dataset_fps == 30
    assert policy.dataset_cameras == {"front": (480, 640, 30), "wrist": (480, 640, 30)}


def test_missing_folder_is_refused_before_lerobot_sees_it(tmp_path: Path) -> None:
    # LeRobot would read a non-folder path as a Hub repo id and download it.
    with pytest.raises(PolicyError, match="not a folder"):
        load_policy(tmp_path / "nope")


@pytest.mark.parametrize(
    ("option", "missing"),
    [
        ("weights", "model.safetensors"),
        ("train_config", "train_config.json"),
        # LeRobot would fail on these only after connecting the robot.
        ("processors", "policy_preprocessor.json"),
    ],
)
def test_missing_checkpoint_files_are_named(
    make_policy: MakePolicy, option: str, missing: str
) -> None:
    path = make_policy(**{option: False})
    with pytest.raises(PolicyError, match=missing):
        load_policy(path)


def test_missing_policy_config_is_named(make_policy: MakePolicy) -> None:
    path = make_policy()
    (path / "config.json").unlink()
    with pytest.raises(PolicyError, match="config.json"):
        load_policy(path)


def test_a_config_that_is_not_a_policy_is_refused(make_policy: MakePolicy) -> None:
    path = make_policy()
    (path / "config.json").write_text(json.dumps({"type": "not_a_policy"}))
    with pytest.raises(PolicyError, match="not a LeRobot policy config"):
        load_policy(path)


def test_dataset_root_null_falls_back_to_lerobot_home(
    make_policy: MakePolicy, tmp_path: Path
) -> None:
    path = make_policy(record_dataset_root=False)
    home = tmp_path / "datasets"
    (home / "local").mkdir()
    (home / "pick_cube").rename(home / "local" / "pick_cube")
    policy = load_policy(path, lerobot_home=home)
    assert policy.dataset_root == home / "local" / "pick_cube"


def test_missing_training_dataset_is_refused_with_a_hint(
    make_policy: MakePolicy, tmp_path: Path
) -> None:
    path = make_policy(record_dataset_root=False)
    with pytest.raises(PolicyError, match="--train-dataset"):
        load_policy(path, lerobot_home=tmp_path / "empty")


def test_train_dataset_override_wins(make_policy: MakePolicy, tmp_path: Path) -> None:
    path = make_policy(record_dataset_root=False)
    policy = load_policy(path, train_dataset=tmp_path / "datasets" / "pick_cube")
    assert policy.dataset_fps == 30


def test_matching_cameras_have_no_problems(make_policy: MakePolicy) -> None:
    assert camera_problems(CONFIG, load_policy(make_policy())) == []


def test_a_renamed_camera_is_a_problem(make_policy: MakePolicy) -> None:
    renamed = {"top": (480, 640), "wrist": (480, 640)}
    policy = load_policy(make_policy(cameras=renamed, dataset_cameras=renamed))
    problems = camera_problems(CONFIG, policy)
    assert any("front" in p and "top" in p for p in problems)


def test_a_missing_camera_is_a_problem(make_policy: MakePolicy) -> None:
    one = {"front": (480, 640)}
    policy = load_policy(make_policy(cameras=one, dataset_cameras=one))
    problems = camera_problems(CONFIG, policy)
    # Named once against the policy and once against its training dataset.
    assert len(problems) == 2
    assert all("wrist" in p for p in problems)


def test_a_resized_camera_is_a_problem(make_policy: MakePolicy) -> None:
    small = {"front": (240, 320), "wrist": (480, 640)}
    policy = load_policy(make_policy(cameras=small, dataset_cameras=small))
    problems = camera_problems(CONFIG, policy)
    assert any("front" in p and "640x480" in p and "320x240" in p for p in problems)


def test_a_dataset_resolution_that_differs_is_a_problem(
    make_policy: MakePolicy,
) -> None:
    small = {"front": (240, 320), "wrist": (480, 640)}
    policy = load_policy(make_policy(dataset_cameras=small))
    problems = camera_problems(CONFIG, policy)
    assert any("front" in p and "dataset" in p for p in problems)


def test_a_different_fps_is_a_problem(make_policy: MakePolicy) -> None:
    policy = load_policy(make_policy(dataset_fps=15))
    problems = camera_problems(CONFIG, policy)
    assert any("30 fps" in p and "15 fps" in p for p in problems)


def test_run_name_comes_from_the_training_run(tmp_path: Path) -> None:
    path = tmp_path / "act_pick_cube_20261101" / "checkpoints" / "last"
    assert run_name(path / "pretrained_model") == (
        "act_pick_cube_20261101",
        "last",
    )
    assert run_name(tmp_path / "my policy!" / "pretrained_model") == (
        "my_policy_",
        "",
    )


def test_run_name_skips_so101_trains_lerobot_folder(tmp_path: Path) -> None:
    # so101-train writes outputs/train/<run>/lerobot/checkpoints/<step>/...
    run = tmp_path / "outputs" / "train" / "20261023T140509Z_cube"
    path = run / "lerobot" / "checkpoints" / "last" / "pretrained_model"
    assert run_name(path) == ("20261023T140509Z_cube", "last")


@pytest.mark.parametrize(
    ("available", "expected"),
    [
        ({"cuda", "mps", "cpu"}, "cuda"),
        ({"mps", "cpu"}, "mps"),
        ({"cpu"}, "cpu"),
    ],
)
def test_auto_device_prefers_cuda_then_mps_then_cpu(
    available: set[str], expected: str
) -> None:
    assert select_device("auto", available) == expected


def test_an_unavailable_device_is_refused() -> None:
    with pytest.raises(PolicyError, match="cuda is not available"):
        select_device("cuda", {"mps", "cpu"})


def test_loads_in_a_fresh_process(make_policy: MakePolicy) -> None:
    # In tests, conftest's import of ACTConfig registers the "act" type; the
    # console script has no such import. A fresh interpreter, with the same
    # network guard, shows what so101-eval sees.
    path = make_policy()
    code = (
        "import socket, sys\n"
        "def refuse(*a, **k): raise AssertionError('network')\n"
        "socket.socket.connect = refuse\n"
        "socket.getaddrinfo = refuse\n"
        "from pathlib import Path\n"
        "from act_policy.policy_check import load_policy\n"
        "print(load_policy(Path(sys.argv[1])).policy_type)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code, str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    assert result.stdout.strip().splitlines()[-1] == "act"
