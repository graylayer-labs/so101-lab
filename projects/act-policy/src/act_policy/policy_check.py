"""Pre-flight checks on a trained policy before it drives the follower.

Paths are relative to ``site-packages/lerobot`` (0.6.1).

A checkpoint folder is what ``lerobot-train`` writes to
``checkpoints/<step>/pretrained_model/`` (common/train_utils.py L119-126):
``config.json`` (the policy config), ``model.safetensors`` (the weights) and
``train_config.json`` (the training run's config, with the dataset it used).
All three are required here.

- The folder is checked before LeRobot sees it: ``from_pretrained`` reads a
  path that is not a folder as a Hub repo id and downloads it
  (configs/policies.py L187-205).
- ``config.json`` is loaded with LeRobot's own
  ``PreTrainedConfig.from_pretrained``, the call ``lerobot-rollout`` makes
  (rollout/configs.py L352-356); anything it refuses is not a policy.
- The cameras the policy was trained on are its ``VISUAL`` input features,
  ``observation.images.<name>`` with shape ``(channels, height, width)``.
  ``lerobot-rollout`` only refuses camera names when neither set contains
  the other (rollout/context.py L382-401), and never checks the size or fps;
  a renamed, resized or slower camera breaks ACT or degrades it silently.
- The training dataset is ``train_config.json``'s ``dataset.root``, or
  ``$HF_LEROBOT_HOME/<repo_id>`` when that is null (configs/default.py
  L35-37). Its ``meta/info.json`` gives ``fps`` and, per camera feature,
  ``shape`` with ``names`` (``height, width, channels`` as
  ``hw_to_dataset_features`` writes it), and ``info.video.fps`` once videos
  are encoded.

The camera check compares ``configs/local.yaml`` with both: names, width x
height, and fps. Any difference is refused.
"""

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from so101.machine_config import MachineConfig

POLICY_CONFIG = "config.json"
WEIGHTS = "model.safetensors"
TRAIN_CONFIG = "train_config.json"
INFO_FILE = Path("meta") / "info.json"
IMAGE_PREFIX = "observation.images."
DEVICE_ORDER = ("cuda", "mps", "cpu")
_UNSAFE = re.compile(r"[^A-Za-z0-9_.-]")


class PolicyError(Exception):
    """The checkpoint or its training dataset cannot be used."""


@dataclass(frozen=True)
class Policy:
    path: Path
    policy_type: str
    cameras: dict[str, tuple[int, int]]  # name -> (height, width)
    dataset_repo_id: str
    dataset_root: Path
    dataset_fps: int
    dataset_cameras: dict[str, tuple[int, int, int]]  # name -> (h, w, fps)
    n_action_steps: int | None


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as err:
        raise PolicyError(f"{path}: cannot be read as JSON: {err}") from err
    if not isinstance(data, dict):
        raise PolicyError(f"{path}: expected a JSON object")
    return data


def _policy_config(path: Path) -> Any:
    """LeRobot's own loader; imported late (it pulls in torch).

    Importing ``lerobot.policies`` registers the policy config types
    (policies/__init__.py L17-35); without it ``from_pretrained`` knows no
    type at all. ``lerobot-rollout`` gets them by importing it too
    (rollout/context.py L38).
    """
    import lerobot.policies  # noqa: F401
    from lerobot.configs.policies import PreTrainedConfig

    try:
        return PreTrainedConfig.from_pretrained(path)
    except Exception as err:  # draccus raises many types; all mean "not a policy"
        raise PolicyError(
            f"{path / POLICY_CONFIG} is not a LeRobot policy config: {err}"
        ) from err


def _default_lerobot_home() -> Path:
    from lerobot.utils.constants import HF_LEROBOT_HOME

    return HF_LEROBOT_HOME


def _image_size(feature: dict[str, Any]) -> tuple[int, int]:
    shape = list(feature.get("shape") or [])
    names = list(feature.get("names") or [])
    if len(shape) != 3:
        raise ValueError(f"expected a 3-axis shape, got {shape}")
    if "height" in names and "width" in names:
        return int(shape[names.index("height")]), int(shape[names.index("width")])
    return int(shape[0]), int(shape[1])  # (h, w, c), as hw_to_dataset_features


def _dataset_cameras(info_path: Path) -> tuple[int, dict[str, tuple[int, int, int]]]:
    info = _read_json(info_path)
    try:
        fps = int(info["fps"])
        cameras = {}
        for key, feature in dict(info["features"]).items():
            if not key.startswith(IMAGE_PREFIX):
                continue
            height, width = _image_size(feature)
            video = feature.get("info") or {}
            cameras[key.removeprefix(IMAGE_PREFIX)] = (
                height,
                width,
                int(video.get("video.fps", fps)),
            )
    except (KeyError, TypeError, ValueError) as err:
        raise PolicyError(f"{info_path}: unexpected dataset metadata: {err}") from err
    return fps, cameras


def load_policy(
    path: Path,
    *,
    train_dataset: Path | None = None,
    lerobot_home: Path | None = None,
) -> Policy:
    """Check the checkpoint folder and read what it was trained on.

    ``train_dataset`` overrides the dataset root from ``train_config.json``.
    """
    if not path.is_dir():
        raise PolicyError(f"policy {path} is not a folder")
    missing = [
        n for n in (POLICY_CONFIG, WEIGHTS, TRAIN_CONFIG) if not (path / n).is_file()
    ]
    if missing:
        raise PolicyError(
            f"policy {path} is missing {', '.join(missing)}; pass a "
            "checkpoints/<step>/pretrained_model folder written by lerobot-train"
        )
    config = _policy_config(path)
    cameras = {}
    for key, feature in config.input_features.items():
        if getattr(feature.type, "name", str(feature.type)) != "VISUAL":
            continue
        _channels, height, width = feature.shape
        cameras[key.removeprefix(IMAGE_PREFIX)] = (int(height), int(width))

    train = _read_json(path / TRAIN_CONFIG)
    dataset = train.get("dataset") or {}
    repo_id = str(dataset.get("repo_id") or "")
    if train_dataset is not None:
        root = train_dataset.expanduser()
    elif dataset.get("root"):
        root = Path(dataset["root"]).expanduser()
    else:
        home = lerobot_home if lerobot_home is not None else _default_lerobot_home()
        root = home / repo_id
    info_path = root / INFO_FILE
    if not info_path.is_file():
        raise PolicyError(
            f"training dataset metadata not found: {info_path} (dataset "
            f"{repo_id!r} from {path / TRAIN_CONFIG}). Pass --train-dataset "
            "with the folder the policy was trained on."
        )
    fps, dataset_cameras = _dataset_cameras(info_path)
    return Policy(
        path=path,
        policy_type=str(config.type),
        cameras=cameras,
        dataset_repo_id=repo_id,
        dataset_root=root,
        dataset_fps=fps,
        dataset_cameras=dataset_cameras,
        n_action_steps=getattr(config, "n_action_steps", None),
    )


def _names(names: Iterable[str]) -> str:
    return ", ".join(sorted(names)) or "none"


def camera_problems(config: MachineConfig, policy: Policy) -> list[str]:
    """Every way the configured cameras differ from what the policy saw."""
    problems = []
    local = set(config.cameras)
    for label, names in (
        ("the policy", set(policy.cameras)),
        ("the training dataset", set(policy.dataset_cameras)),
    ):
        if names != local:
            problems.append(
                f"camera names differ: configs/local.yaml has {_names(local)}; "
                f"{label} has {_names(names)}"
            )
    for name in sorted(local):
        cam = config.cameras[name]
        here = f"{cam.width}x{cam.height}"
        if name in policy.cameras:
            height, width = policy.cameras[name]
            if (height, width) != (cam.height, cam.width):
                problems.append(
                    f"camera {name}: configs/local.yaml is {here}; the policy "
                    f"was trained on {width}x{height}"
                )
        if name in policy.dataset_cameras:
            height, width, fps = policy.dataset_cameras[name]
            if (height, width) != (cam.height, cam.width):
                problems.append(
                    f"camera {name}: configs/local.yaml is {here}; the training "
                    f"dataset has {width}x{height}"
                )
            if fps != cam.fps:
                problems.append(
                    f"camera {name}: configs/local.yaml is {cam.fps} fps; the "
                    f"training dataset has {fps} fps"
                )
    return problems


def run_name(path: Path) -> tuple[str, str]:
    """``(training run, checkpoint)`` from ``.../<run>/checkpoints/<step>/...``.

    Without a ``checkpoints`` folder in the path, the run is the folder name
    (its parent's for ``pretrained_model``) and the checkpoint is ''. Only
    letters, digits, ``_``, ``.`` and ``-`` are kept, so the run can name
    a folder and a dataset.
    """
    parts = path.parts
    if "checkpoints" in parts[:-1]:
        index = len(parts) - 1 - parts[::-1].index("checkpoints")
        if index >= 1 and index + 1 < len(parts):
            return _UNSAFE.sub("_", parts[index - 1]), parts[index + 1]
    name = path.parent.name if path.name == "pretrained_model" else path.name
    return _UNSAFE.sub("_", name), ""


def available_devices() -> set[str]:
    """The torch devices this machine has; imported late (torch is slow)."""
    import torch

    found = {"cpu"}
    if torch.cuda.is_available():
        found.add("cuda")
    if torch.backends.mps.is_available():
        found.add("mps")
    return found


def select_device(requested: str, available: set[str]) -> str:
    """``auto``: cuda, then mps, then cpu. A named device must be available."""
    if requested == "auto":
        return next(d for d in DEVICE_ORDER if d in available or d == "cpu")
    if requested not in available:
        raise PolicyError(
            f"device {requested} is not available here (found: {_names(available)})"
        )
    return requested
