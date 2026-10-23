"""``rollout_argv``: a snapshot, then LeRobot 0.6.1's own parser, in process.

The parse mirrors ``lerobot.configs.parser.wrap`` (configs/parser.py
L382-436), the decorator on ``lerobot_rollout.rollout``: ``--policy.*`` is
filtered out of the draccus args, and ``RolloutConfig.__post_init__`` reads
``--policy.path`` and the other ``--policy.*`` overrides back from
``sys.argv`` (rollout/configs.py L344-357). So ``sys.argv`` is set to the
argv. Parsing loads the policy's ``config.json`` from the folder; no robot is
built and nothing connects.
"""

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import draccus
import pytest
from lerobot.configs import parser
from lerobot.robots.so_follower import SOFollowerRobotConfig
from lerobot.rollout.configs import EpisodicStrategyConfig, RolloutConfig

# The script module itself: importing it registers the camera, robot and
# teleop config types exactly as ``lerobot-rollout`` does
# (scripts/lerobot_rollout.py L155-193).
from lerobot.scripts import lerobot_rollout

from act_policy.rollout_argv import rollout_argv
from hw_setup.lerobot_argv import arm_args, cameras_value
from so101.arm import ArmRole
from so101.machine_config import load_machine_config

REPO = Path(__file__).parents[3]
CONFIG = load_machine_config(REPO / "configs" / "example.yaml")
ROOT = REPO.resolve()
MakePolicy = Callable[..., Path]


def build(policy: Path, dataset_root: Path, **options: Any) -> list[str]:
    kwargs: dict[str, Any] = {
        "policy_path": policy,
        "repo_id": "local/rollout_act_pick_cube",
        "dataset_root": dataset_root,
        "task": "Pick the cube and place it in the bin",
        "fps": 30,
        "device": "cpu",
        "max_relative_target": 5.0,
    }
    return rollout_argv(CONFIG, ROOT, **(kwargs | options))


def parse(monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> RolloutConfig:
    assert lerobot_rollout.RolloutConfig is RolloutConfig
    monkeypatch.setattr(sys, "argv", argv)
    args = parser.filter_path_args(RolloutConfig.__get_path_fields__(), argv[1:])
    return draccus.parse(config_class=RolloutConfig, args=args)


def test_snapshot(tmp_path: Path) -> None:
    policy = tmp_path / "pretrained_model"
    root = tmp_path / "rollout_act_pick_cube"
    argv = build(policy, root, episode_time_s=30.0)
    assert argv == [
        "lerobot-rollout",
        "--strategy.type=episodic",
        f"--policy.path={policy}",
        "--policy.device=cpu",
        "--device=cpu",
        *arm_args(CONFIG, ArmRole.FOLLOWER, ROOT),
        f"--robot.cameras={cameras_value(CONFIG)}",
        "--robot.max_relative_target=5.0",
        "--dataset.repo_id=local/rollout_act_pick_cube",
        "--dataset.single_task=Pick the cube and place it in the bin",
        f"--dataset.root={root}",
        "--dataset.num_episodes=1",
        "--dataset.fps=30",
        "--dataset.push_to_hub=false",
        "--dataset.no_stamp=true",
        "--dataset.episode_time_s=30.0",
        "--fps=30",
        "--display_data=false",
    ]


def test_no_teleop_flag_is_ever_built(tmp_path: Path) -> None:
    argv = build(tmp_path / "p", tmp_path / "d", resume=True, display_data=True)
    assert not any(a.startswith("--teleop") for a in argv)


def test_lerobot_parses_it(
    monkeypatch: pytest.MonkeyPatch, make_policy: MakePolicy, tmp_path: Path
) -> None:
    policy = make_policy(device="cuda")
    root = tmp_path / "eval"
    cfg = parse(monkeypatch, build(policy, root, episode_time_s=20.0))

    assert isinstance(cfg.strategy, EpisodicStrategyConfig)
    assert cfg.strategy.reset_to_initial_position is True
    assert cfg.teleop is None
    assert cfg.return_to_initial_position is True
    assert cfg.resume is False
    assert cfg.fps == 30
    assert cfg.display_data is False

    assert cfg.policy is not None
    assert cfg.policy.type == "act"
    assert cfg.policy.pretrained_path == str(policy)
    # The checkpoint said cuda; the flags win, for the policy and the runtime.
    assert cfg.policy.device == "cpu"
    assert cfg.device == "cpu"

    robot = cfg.robot
    assert isinstance(robot, SOFollowerRobotConfig)
    assert robot.port == CONFIG.arms[ArmRole.FOLLOWER].port
    assert robot.id == "main"
    assert robot.calibration_dir == ROOT / "hardware" / "calibration" / "follower"
    assert robot.max_relative_target == 5.0
    assert set(robot.cameras) == {"front", "wrist"}
    front = robot.cameras["front"]
    assert (front.width, front.height, front.fps) == (640, 480, 30)

    dataset = cfg.dataset
    assert dataset is not None
    assert dataset.repo_id == "local/rollout_act_pick_cube"
    assert dataset.single_task == "Pick the cube and place it in the bin"
    assert cfg.task == dataset.single_task  # rollout/configs.py L368-370
    assert Path(dataset.root or "") == root
    assert dataset.num_episodes == 1
    assert dataset.episode_time_s == 20.0
    assert dataset.fps == 30
    assert dataset.push_to_hub is False
    assert dataset.no_stamp is True


def test_lerobot_parses_resume_and_display(
    monkeypatch: pytest.MonkeyPatch, make_policy: MakePolicy, tmp_path: Path
) -> None:
    argv = build(
        make_policy(),
        tmp_path / "eval",
        resume=True,
        display_data=True,
        reset_time_s=10.0,
        max_relative_target=None,
    )
    cfg = parse(monkeypatch, argv)
    assert cfg.resume is True
    assert cfg.display_data is True
    assert cfg.dataset is not None and cfg.dataset.reset_time_s == 10.0
    assert isinstance(cfg.robot, SOFollowerRobotConfig)
    assert cfg.robot.max_relative_target is None


def test_rollout_names_must_start_with_rollout(tmp_path: Path) -> None:
    # LeRobot refuses other names when it creates the dataset, after it has
    # loaded the policy and connected the robot (rollout/context.py L428-433).
    with pytest.raises(ValueError, match="rollout_"):
        build(tmp_path / "p", tmp_path / "d", repo_id="local/eval_act")
