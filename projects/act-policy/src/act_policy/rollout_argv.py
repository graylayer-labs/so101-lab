"""Build the LeRobot 0.6.1 ``lerobot-rollout`` command for one eval episode.

A pure function, like the builders in ``hw_setup.lerobot_argv``: it returns
the argv and runs nothing. The follower flags (``--robot.*``, cameras, the
movement cap) are the ones the hw-setup wrappers build. Paths below are
relative to ``site-packages/lerobot``; ``tests/test_rollout_argv.py`` parses
every argv with LeRobot's own ``RolloutConfig``.

- ``--strategy.type=episodic``: ``EpisodicStrategyConfig``, registered at
  rollout/configs.py L124-126. It records ``dataset.num_episodes`` episodes
  of at most ``dataset.episode_time_s`` (L129-130). Right arrow ends an
  episode, left arrow re-records it, Escape stops (L132-135).
- No ``--teleop.*``: ``RolloutConfig.teleop`` defaults to None (L225); only
  DAgger requires one (L276-277). Without a teleop the follower is driven
  back to the pose captured at startup between episodes
  (``reset_to_initial_position``, L142-145; strategies/episodic.py L166-168
  and L188-190) and at the end (``return_to_initial_position``, configs.py
  L262-265; strategies/core.py L119-128). The startup pose is read at
  connect (rollout/context.py L305-306), so the follower must start at a
  safe pose. The leader is not needed.
- ``--policy.path``: read in ``RolloutConfig.__post_init__`` with
  ``PreTrainedConfig.from_pretrained`` (configs.py L344-357). A path that is
  not a folder is treated as a Hub repo id and downloaded
  (configs/policies.py L187-205), so the caller checks the folder first.
- ``--policy.device`` and ``--device``: ``--policy.*`` flags are passed to
  ``from_pretrained`` as overrides (configs.py L347-348), so the checkpoint's
  own device (say ``cuda`` from a cloud run) is replaced. ``--device``
  (L243) is what the policy, processors and inference engine use
  (context.py L270, L472, L503); left unset it falls back to the policy's
  (configs.py L376-383). Both are passed, the same value.
- ``--dataset.*``: ``DatasetRecordConfig`` (configs/dataset.py L25-43,
  ``no_stamp`` L76). Episodic needs ``--dataset.repo_id`` (rollout/configs.py
  L279-290). A new rollout dataset must be named ``rollout_*``
  (rollout/context.py L428-433); LeRobot checks that only after loading the
  policy and connecting the robot, so it is checked here first.
  ``--dataset.push_to_hub=false`` always: it defaults to True
  (configs/dataset.py L43) and the episodic teardown pushes when it is set
  (strategies/episodic.py L323-333). ``--dataset.no_stamp=true`` keeps the
  repo id as given (configs/dataset.py L78-89, called at context.py L434).
  ``--dataset.root`` is where the eval videos are written
  (``LeRobotDataset.create``/``resume``, context.py L406-449).
- ``--fps`` (configs.py L240) is the control-loop rate and
  ``--dataset.fps`` the rate the dataset is created with (context.py L438);
  both are the training dataset's fps.
- ``--resume=true`` (configs.py L257) adds episodes to the dataset at the
  root (``LeRobotDataset.resume``, context.py L406-407).
- ``--display_data`` (configs.py L245).
- ``--dataset.num_episodes=1``: ``so101-eval`` runs one rollout per trial so
  each episode can be scored at a prompt when it ends. With one episode the
  reset phase is skipped (strategies/episodic.py L134-137) except after a
  left-arrow re-record.
"""

from pathlib import Path

from hw_setup.lerobot_argv import arm_args, cameras_value, max_relative_target_arg
from so101.arm import ArmRole
from so101.machine_config import MachineConfig

ROLLOUT_PREFIX = "rollout_"


def rollout_argv(
    config: MachineConfig,
    repo_root: Path,
    *,
    policy_path: Path,
    repo_id: str,
    dataset_root: Path,
    task: str,
    fps: int,
    device: str,
    max_relative_target: float | None,
    episode_time_s: float | None = None,
    reset_time_s: float | None = None,
    resume: bool = False,
    display_data: bool = False,
) -> list[str]:
    """``lerobot-rollout --strategy.type=episodic`` for one episode.

    The follower only, with the configured cameras and the movement cap
    (``hw_setup.lerobot_argv.max_relative_target_arg``). Options left as
    None take LeRobot's defaults (60 s each, configs/dataset.py L35, L37).
    """
    name = repo_id.split("/", 1)[-1]
    if not name.startswith(ROLLOUT_PREFIX):
        raise ValueError(
            f"repo id {repo_id!r}: LeRobot's rollout needs a dataset name "
            f"starting with {ROLLOUT_PREFIX!r}"
        )
    argv = [
        "lerobot-rollout",
        "--strategy.type=episodic",
        f"--policy.path={policy_path}",
        f"--policy.device={device}",
        f"--device={device}",
        *arm_args(config, ArmRole.FOLLOWER, repo_root),
    ]
    if config.cameras:
        argv.append(f"--robot.cameras={cameras_value(config)}")
    argv += [
        max_relative_target_arg(max_relative_target),
        f"--dataset.repo_id={repo_id}",
        f"--dataset.single_task={task}",
        f"--dataset.root={dataset_root}",
        "--dataset.num_episodes=1",
        f"--dataset.fps={fps}",
        "--dataset.push_to_hub=false",
        "--dataset.no_stamp=true",
    ]
    optional = {"episode_time_s": episode_time_s, "reset_time_s": reset_time_s}
    argv += [f"--dataset.{k}={v}" for k, v in optional.items() if v is not None]
    argv += [f"--fps={fps}", f"--display_data={str(display_data).lower()}"]
    if resume:
        argv.append("--resume=true")
    return argv
