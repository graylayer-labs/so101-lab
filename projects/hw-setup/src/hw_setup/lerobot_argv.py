"""Build LeRobot 0.6.1 command lines from the machine config.

Each builder is a pure function: it returns the argv as a list of strings and
runs nothing. The follower arm goes to ``--robot.*`` and the leader arm to
``--teleop.*``, as LeRobot's scripts expect.

Flag names were checked against the installed lerobot 0.6.1 (paths relative to
``site-packages/lerobot``) and by `uv run lerobot-<cmd> --help`; the tests also
parse every argv with LeRobot's own draccus config classes.

- ``--robot.type`` / ``--teleop.type``: ``so101_follower`` is registered in
  robots/so_follower/config_so_follower.py L56, ``so101_leader`` in
  teleoperators/so_leader/config_so_leader.py L39.
- ``--robot.port`` / ``--teleop.port``: config_so_follower.py L29,
  config_so_leader.py L27.
- ``--robot.id``, ``--robot.calibration_dir``: robots/config.py L25, L27.
  ``--teleop.id``, ``--teleop.calibration_dir``: teleoperators/config.py L25,
  L27. LeRobot reads ``<calibration_dir>/<id>.json``.
- ``--robot.cameras``: config_so_follower.py L39, a ``dict[str, CameraConfig]``
  given as a YAML-style dict; ``type: opencv`` is registered in
  cameras/opencv/configuration_opencv.py L23 with ``index_or_path`` (L61) and
  ``fps``, ``width``, ``height`` from cameras/configs.py L61-63.
- ``--display_data``: scripts/lerobot_teleoperate.py L143 and
  scripts/lerobot_record.py L177.
- ``--dataset.repo_id``, ``single_task``, ``root``, ``fps``,
  ``episode_time_s``, ``reset_time_s``, ``num_episodes``, ``push_to_hub``:
  configs/dataset.py L27-43 (``DatasetRecordConfig``); ``--dataset.no_stamp``:
  configs/dataset.py L76. ``--resume``: scripts/lerobot_record.py L190.
"""

import shlex
from pathlib import Path

from so101.arm import ArmRole
from so101.machine_config import MachineConfig

FOLLOWER_TYPE = "so101_follower"
LEADER_TYPE = "so101_leader"
CALIBRATION_ROOT = Path("hardware") / "calibration"

_PREFIX = {ArmRole.FOLLOWER: "robot", ArmRole.LEADER: "teleop"}
_TYPE = {ArmRole.FOLLOWER: FOLLOWER_TYPE, ArmRole.LEADER: LEADER_TYPE}


class CalibrationRootError(ValueError):
    """The repo root given to a builder is not the workspace root."""


def calibration_dir(repo_root: Path, role: ArmRole) -> Path:
    """The folder LeRobot reads ``<id>.json`` from for this role.

    Same layout as ``so101.calibration_path``: ``hardware/calibration/<role>``.
    The path is absolute, so the command works from any directory. A root
    without ``hardware/calibration/`` is rejected: LeRobot would find no
    ``<id>.json`` there and silently start a fresh calibration.
    """
    root = repo_root.resolve()
    if not (root / CALIBRATION_ROOT).is_dir():
        raise CalibrationRootError(
            f"{root} has no {CALIBRATION_ROOT}/ folder; "
            "pass the so101-lab workspace root as repo_root"
        )
    return root / CALIBRATION_ROOT / role.value


def _arm_args(config: MachineConfig, role: ArmRole, repo_root: Path) -> list[str]:
    arm = config.arms[role]
    prefix = _PREFIX[role]
    return [
        f"--{prefix}.type={_TYPE[role]}",
        f"--{prefix}.port={arm.port}",
        f"--{prefix}.id={arm.arm_id}",
        f"--{prefix}.calibration_dir={calibration_dir(repo_root, role)}",
    ]


def cameras_value(config: MachineConfig) -> str:
    """The cameras as the dict LeRobot's ``--robot.cameras`` parses."""
    entries = [
        f"{name}: {{type: opencv, index_or_path: {cam.index}, "
        f"width: {cam.width}, height: {cam.height}, fps: {cam.fps}}}"
        for name, cam in config.cameras.items()
    ]
    return "{" + ", ".join(entries) + "}"


def _pair_args(config: MachineConfig, repo_root: Path, cameras: bool) -> list[str]:
    args = _arm_args(config, ArmRole.FOLLOWER, repo_root)
    if cameras and config.cameras:
        args.append(f"--robot.cameras={cameras_value(config)}")
    return args + _arm_args(config, ArmRole.LEADER, repo_root)


def setup_motors_argv(
    config: MachineConfig, role: ArmRole, repo_root: Path
) -> list[str]:
    """``lerobot-setup-motors`` for one arm."""
    return ["lerobot-setup-motors", *_arm_args(config, role, repo_root)]


def calibrate_argv(config: MachineConfig, role: ArmRole, repo_root: Path) -> list[str]:
    """``lerobot-calibrate`` for one arm. Cameras are left out: not needed."""
    return ["lerobot-calibrate", *_arm_args(config, role, repo_root)]


def teleoperate_argv(
    config: MachineConfig,
    repo_root: Path,
    *,
    cameras: bool = True,
    display_data: bool = False,
) -> list[str]:
    """``lerobot-teleoperate``: the leader drives the follower."""
    argv = ["lerobot-teleoperate", *_pair_args(config, repo_root, cameras)]
    if display_data:
        argv.append("--display_data=true")
    return argv


def record_argv(
    config: MachineConfig,
    repo_root: Path,
    *,
    repo_id: str,
    single_task: str,
    num_episodes: int,
    dataset_root: Path | None = None,
    episode_time_s: float | None = None,
    reset_time_s: float | None = None,
    fps: int | None = None,
    push_to_hub: bool | None = None,
    no_stamp: bool = False,
    cameras: bool = True,
    display_data: bool = False,
    resume: bool = False,
) -> list[str]:
    """``lerobot-record`` with the given dataset options.

    Options left as None are not passed, so LeRobot's defaults apply (note
    that LeRobot pushes to the Hub by default). ``no_stamp`` stops LeRobot
    appending a date-time tag to ``repo_id`` on a new dataset. No safety
    rules are applied.
    """
    argv = ["lerobot-record", *_pair_args(config, repo_root, cameras)]
    argv += [
        f"--dataset.repo_id={repo_id}",
        f"--dataset.single_task={single_task}",
        f"--dataset.num_episodes={num_episodes}",
    ]
    optional = {
        "root": dataset_root,
        "episode_time_s": episode_time_s,
        "reset_time_s": reset_time_s,
        "fps": fps,
    }
    argv += [f"--dataset.{k}={v}" for k, v in optional.items() if v is not None]
    if push_to_hub is not None:
        argv.append(f"--dataset.push_to_hub={str(push_to_hub).lower()}")
    if no_stamp:
        argv.append("--dataset.no_stamp=true")
    if display_data:
        argv.append("--display_data=true")
    if resume:
        argv.append("--resume=true")
    return argv


def format_command(argv: list[str]) -> str:
    """The argv as one line to paste into a shell (for ``--dry-run``)."""
    return shlex.join(argv)
