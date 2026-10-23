"""``so101-train``: train ACT on a local dataset with ``lerobot-train``.

The command is built by a pure function, ``train_argv``, and every flag was
checked against LeRobot 0.6.1's ``TrainPipelineConfig`` (paths relative to
``site-packages/lerobot``); the tests parse the argv with LeRobot's own
draccus parser and run its ``validate()``.

- ``--policy.type=act``: registered at policies/act/configuration_act.py L22
  (``register_subclass("act")``). ``--policy.device``, ``--policy.use_amp``,
  ``--policy.push_to_hub``: configs/policies.py L62, L65, L70.
- ``--policy.push_to_hub=false`` is always passed. The default is True
  (policies.py L70), and with no ``policy.repo_id`` ``validate()`` fails at
  start (configs/train.py L283-289).
- ``--wandb.enable=false`` is always passed. It is already the default
  (configs/default.py L82); passing it makes the command say what it does.
- ``--dataset.repo_id`` is required (default.py L31); ``--dataset.root``
  is always passed, resolved (default.py L37). With a root the repo_id is
  only a name. lerobot-train still tries the Hub if ``data/`` or
  ``videos/`` is missing, so it runs with ``HF_HUB_OFFLINE=1``.
- ``--policy.device``: LeRobot picks cuda, then mps, then xpu, then cpu when
  it is unset, and silently falls back when the one asked for is missing
  (policies.py L86-89, utils/device_utils.py L22-35). Here the default is
  cuda, then mps, then cpu, and an unavailable ``--device`` is refused.
  On cuda ``--policy.use_amp=true`` is added; AMP is not available on mps
  (device_utils.py L126-131).
- ``--steps``, ``--batch_size``, ``--save_freq``, ``--log_freq``,
  ``--job_name``, ``--output_dir``: configs/train.py L111, L102, L123,
  L114, L87, L86. The defaults come from this project's run config
  (``configs/act_pick_cube.yaml``), whose steps and batch size are LeRobot's.
- ``--output_dir`` must not exist unless ``--resume=true``
  (configs/train.py L259-263). So each run gets a fresh folder
  ``outputs/train/<UTC time>_<dataset name>/``, refused if it exists; this
  tool writes ``dataset.json`` there and points ``--output_dir`` at the
  ``lerobot/`` folder inside it, which lerobot-train creates.

``dataset.json`` records the dataset's own metadata (repo_id, root, episode
and frame counts, fps, robot type and camera features), so the eval tool can
check that its cameras and fps match the ones the policy was trained on.
It is read with ``LeRobotDatasetMetadata`` from local files only: missing
metadata is refused first, because LeRobot would otherwise download
``meta/`` from the Hub (datasets/dataset_metadata.py L134-148).
"""

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, fields
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from hw_setup.lerobot_argv import format_command
from hw_setup.record import default_lerobot_home, missing_metadata
from hw_setup.workspace import WorkspaceError, find_workspace_root

PROG = "so101-train"
POLICY_TYPE = "act"
DEFAULT_RUN_CONFIG = (
    Path(__file__).resolve().parents[2] / "configs" / "act_pick_cube.yaml"
)
RUNS_DIR = Path("outputs") / "train"
LEROBOT_DIR = "lerobot"
DATASET_RECORD = "dataset.json"
DEVICES = ("cuda", "mps", "cpu")
_REPO_ID = re.compile(r"[^/\s]+/[^/\s]+")

Runner = Callable[[list[str]], int]
DeviceAvailable = Callable[[str], bool]


class RunConfigError(ValueError):
    """The run config file cannot be used."""


class DatasetError(ValueError):
    """The dataset cannot be read from local files."""


@dataclass(frozen=True)
class TrainSettings:
    steps: int
    batch_size: int
    save_freq: int
    log_freq: int


@dataclass(frozen=True)
class RunConfig:
    job_name: str
    train: TrainSettings
    smoke: TrainSettings


def _settings(raw: object, section: str) -> TrainSettings:
    if not isinstance(raw, dict):
        raise RunConfigError(f"{section}: expected a mapping")
    names = [f.name for f in fields(TrainSettings)]
    if sorted(raw) != sorted(names):
        raise RunConfigError(f"{section}: expected exactly the keys {names}")
    for name in names:
        value = raw[name]
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise RunConfigError(f"{section}.{name}: expected a whole number >= 1")
    return TrainSettings(**{name: raw[name] for name in names})


def load_run_config(path: Path) -> RunConfig:
    """Read a run config: ``job_name`` and the ``train`` and ``smoke`` settings."""
    try:
        raw = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError) as err:
        raise RunConfigError(f"{path}: {err}") from err
    if not isinstance(raw, dict):
        raise RunConfigError(f"{path}: expected a mapping")
    job_name = raw.get("job_name")
    if not isinstance(job_name, str) or not job_name.strip():
        raise RunConfigError(f"{path}: job_name must be a non-empty string")
    try:
        return RunConfig(
            job_name=job_name,
            train=_settings(raw.get("train"), "train"),
            smoke=_settings(raw.get("smoke"), "smoke"),
        )
    except RunConfigError as err:
        raise RunConfigError(f"{path}: {err}") from err


def torch_device_available(device: str) -> bool:
    """Whether torch can use ``device`` here (imported late: torch is slow)."""
    import torch

    if device == "cuda":
        return torch.cuda.is_available()
    if device == "mps":
        return torch.backends.mps.is_available()
    return device == "cpu"


def pick_device(available: DeviceAvailable) -> str:
    """The first of cuda, mps and cpu that is available."""
    for device in DEVICES:
        if available(device):
            return device
    return "cpu"


def run_name(repo_id: str, now: datetime) -> str:
    """``<UTC time>_<dataset name>``, e.g. ``20261023T140509Z_so101_pick_cube``."""
    stamp = now.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}_{repo_id.split('/')[-1]}"


def train_argv(
    *,
    repo_id: str,
    dataset_root: Path,
    output_dir: Path,
    device: str,
    settings: TrainSettings,
    job_name: str,
) -> list[str]:
    """``lerobot-train`` for ACT on a local dataset. Runs nothing.

    Paths must be absolute, so the command means the same from any folder.
    """
    for name, path in (("dataset_root", dataset_root), ("output_dir", output_dir)):
        if not path.is_absolute():
            raise ValueError(f"{name} must be an absolute path, got {path}")
    argv = [
        "lerobot-train",
        f"--policy.type={POLICY_TYPE}",
        f"--dataset.repo_id={repo_id}",
        f"--dataset.root={dataset_root}",
        f"--policy.device={device}",
    ]
    if device == "cuda":
        argv.append("--policy.use_amp=true")
    argv += [
        "--policy.push_to_hub=false",
        "--wandb.enable=false",
        f"--steps={settings.steps}",
        f"--batch_size={settings.batch_size}",
        f"--save_freq={settings.save_freq}",
        f"--log_freq={settings.log_freq}",
        f"--output_dir={output_dir}",
        f"--job_name={job_name}",
    ]
    return argv


def read_dataset_record(repo_id: str, dataset_root: Path) -> dict[str, Any]:
    """The dataset's own metadata, read from local files only."""
    if not dataset_root.is_dir():
        raise DatasetError(f"no dataset at {dataset_root}")
    missing = missing_metadata(dataset_root)
    if missing:
        raise DatasetError(
            f"{dataset_root} holds an incomplete dataset (missing: "
            f"{', '.join(missing)}); LeRobot would fetch the metadata from the Hub"
        )
    from lerobot.datasets.dataset_metadata import LeRobotDatasetMetadata

    meta = LeRobotDatasetMetadata(repo_id, root=dataset_root)
    cameras = {key: meta.features[key] for key in meta.camera_keys}
    record = {
        "repo_id": repo_id,
        "root": str(dataset_root),
        "codebase_version": meta.info.codebase_version,
        "robot_type": meta.robot_type,
        "total_episodes": meta.total_episodes,
        "total_frames": meta.total_frames,
        "fps": meta.fps,
        "cameras": cameras,
    }
    # Through JSON, so shapes are lists as they are in meta/info.json.
    return json.loads(json.dumps(record))


def _run(argv: list[str]) -> int:
    """Run ``argv`` with the Hub offline (``HF_HUB_OFFLINE=1``).

    With ``meta/`` complete but ``data/`` or ``videos/`` missing,
    lerobot-train would still look the dataset up on the Hub
    (datasets/lerobot_dataset.py L272-278, L643-675). Offline, it fails
    instead. The ResNet-18 backbone weights come from download.pytorch.org,
    which this does not block.
    """
    env = {**os.environ, "HF_HUB_OFFLINE": "1"}
    return subprocess.run(argv, check=False, env=env).returncode


def _repo_id(text: str) -> str:
    if not _REPO_ID.fullmatch(text):
        raise argparse.ArgumentTypeError(f"expected USER/NAME, got {text!r}")
    return text


def _positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a whole number: {text!r}") from None
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be 1 or more, got {value}")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description=(
            "Train ACT on a local LeRobot dataset with lerobot-train. "
            "Never pushes to the Hugging Face Hub; W&B is off."
        ),
    )
    parser.add_argument(
        "--repo-id", required=True, type=_repo_id, help="dataset name, USER/NAME"
    )
    parser.add_argument(
        "--dataset-root",
        type=Path,
        help="the dataset folder (default: $HF_LEROBOT_HOME/USER/NAME)",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="a short laptop run with the config's smoke settings",
    )
    parser.add_argument("--steps", type=_positive_int, help="override the steps")
    parser.add_argument(
        "--batch-size", type=_positive_int, help="override the batch size"
    )
    parser.add_argument(
        "--device",
        choices=DEVICES,
        help="training device (default: cuda, then mps, then cpu)",
    )
    parser.add_argument(
        "--config",
        type=Path,
        help=f"run config (default: {DEFAULT_RUN_CONFIG.name} in this project)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the plan and the command; create and run nothing",
    )
    return parser


def _settings_for(args: argparse.Namespace, config: RunConfig) -> TrainSettings:
    base = config.smoke if args.smoke else config.train
    steps = args.steps if args.steps is not None else base.steps
    return TrainSettings(
        steps=steps,
        batch_size=args.batch_size if args.batch_size is not None else base.batch_size,
        # A save_freq past the end would only mean the final checkpoint.
        save_freq=min(base.save_freq, steps),
        log_freq=min(base.log_freq, steps),
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    runner: Runner = _run,
    root: Path | None = None,
    lerobot_home: Path | None = None,
    now: datetime | None = None,
    device_available: DeviceAvailable = torch_device_available,
) -> int:
    args = _parser().parse_args(argv)
    try:
        workspace = (root if root is not None else find_workspace_root()).resolve()
        config = load_run_config(args.config or DEFAULT_RUN_CONFIG)
        if args.device is not None and not device_available(args.device):
            raise ValueError(f"{args.device} is not available on this machine")
        device = args.device or pick_device(device_available)
        if args.dataset_root is not None:
            dataset_root = args.dataset_root.expanduser().resolve()
        else:
            home = lerobot_home if lerobot_home is not None else default_lerobot_home()
            dataset_root = (home / args.repo_id).resolve()
        record = read_dataset_record(args.repo_id, dataset_root)
        run_dir = (
            workspace / RUNS_DIR / run_name(args.repo_id, now or datetime.now(UTC))
        )
        if run_dir.exists():
            raise ValueError(f"run folder {run_dir} already exists")
        settings = _settings_for(args, config)
        command = train_argv(
            repo_id=args.repo_id,
            dataset_root=dataset_root,
            output_dir=run_dir / LEROBOT_DIR,
            device=device,
            settings=settings,
            job_name=config.job_name,
        )
    except (WorkspaceError, ValueError) as err:
        print(f"{PROG}: refusing to run: {err}", file=sys.stderr)
        return 1

    cameras = ", ".join(
        f"{key} {'x'.join(str(n) for n in feature['shape'])}"
        for key, feature in record["cameras"].items()
    )
    print(f"Dataset: {args.repo_id}")
    print(f"Dataset root: {dataset_root}")
    print(f"Episodes: {record['total_episodes']} ({record['total_frames']} frames)")
    print(f"FPS: {record['fps']}")
    print(f"Cameras: {cameras or 'none'}")
    print(f"Mode: {'smoke' if args.smoke else 'full'}")
    print(f"Device: {device}")
    print(
        f"Steps: {settings.steps}, batch size: {settings.batch_size}, "
        f"save every {settings.save_freq}, log every {settings.log_freq}"
    )
    print(f"Run folder: {run_dir}")
    print("Push to Hub: no. W&B: off.")
    print(f"Command: {format_command(command)}")
    if args.dry_run:
        print("Dry run: nothing was run.")
        return 0
    try:
        run_dir.mkdir(parents=True)
    except FileExistsError:
        print(f"{PROG}: refusing to run: {run_dir} already exists", file=sys.stderr)
        return 1
    (run_dir / DATASET_RECORD).write_text(json.dumps(record, indent=2) + "\n")
    return runner(command)


def cli() -> None:
    sys.exit(main())
