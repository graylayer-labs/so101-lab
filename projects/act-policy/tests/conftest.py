"""Fixtures for act-policy tests: no test may open a port, a camera or a socket.

The policy folder is written by LeRobot 0.6.1's own savers, so its files are
the ones ``lerobot-train`` leaves in ``checkpoints/<step>/pretrained_model``
(common/train_utils.py L104-129): ``config.json`` from
``PreTrainedConfig._save_pretrained`` (configs/policies.py L165-169),
``train_config.json`` from ``TrainPipelineConfig._save_pretrained``
(configs/train.py L302-304) and ``model.safetensors`` (here a one-tensor file:
nothing loads the weights). The training dataset's ``meta/info.json`` is
written by ``LeRobotDatasetMetadata.create`` from the features LeRobot
derives from the robot (``hw_to_dataset_features``), so its camera entries
have the real shape and names. Nothing is trained here; a real 4-step
checkpoint goes through the eval preflight in ``test_train.py``.
"""

import shutil
import socket
from collections.abc import Callable
from pathlib import Path

import pytest
import serial
import torch
from lerobot.configs.default import DatasetConfig
from lerobot.configs.train import TrainPipelineConfig
from lerobot.configs.types import FeatureType, PolicyFeature
from lerobot.datasets import LeRobotDatasetMetadata
from lerobot.policies.act.configuration_act import ACTConfig
from lerobot.utils.feature_utils import hw_to_dataset_features
from safetensors.torch import save_file

REPO = Path(__file__).parents[3]
EXAMPLE = REPO / "configs" / "example.yaml"
JOINTS = (
    "shoulder_pan",
    "shoulder_lift",
    "elbow_flex",
    "wrist_flex",
    "wrist_roll",
    "gripper",
)
# configs/example.yaml has two cameras, both 640x480 at 30 fps.
CAMERAS = {"front": (480, 640), "wrist": (480, 640)}


@pytest.fixture(autouse=True)
def no_serial_port(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail any test that reaches pyserial's open, the last step to a port."""

    def refuse(self: object, *args: object, **kwargs: object) -> None:
        raise AssertionError("a test tried to open a serial port")

    monkeypatch.setattr(serial.Serial, "open", refuse)


@pytest.fixture(autouse=True)
def no_camera(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail any test that opens a camera through OpenCV.

    LeRobot's OpenCV camera calls ``cv2.VideoCapture`` through the module
    (cameras/opencv/camera_opencv.py L166, L330), so this catches it.
    """
    import cv2

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("a test tried to open a camera")

    monkeypatch.setattr(cv2, "VideoCapture", refuse)


class NetworkUsed(AssertionError):
    pass


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail any test that opens a network connection (the Hub, say).

    A policy path that is not a folder makes LeRobot fetch ``config.json``
    from the Hub (configs/policies.py L187-205); this guard turns that into a
    test failure rather than a download. Host lookups are refused too.
    """

    def refuse(*args: object, **kwargs: object) -> None:
        raise NetworkUsed("a test tried to open a network connection")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A workspace root: both calibrations and configs/local.yaml."""
    root = tmp_path / "ws"
    for arm in ("leader", "follower"):
        target = root / "hardware" / "calibration" / arm
        target.mkdir(parents=True)
        shutil.copy(REPO / "hardware" / "calibration" / arm / "main.json", target)
    (root / "configs").mkdir()
    (root / "configs" / "local.yaml").write_text(EXAMPLE.read_text())
    return root


def write_train_dataset(
    root: Path, cameras: dict[str, tuple[int, int]] = CAMERAS, fps: int = 30
) -> Path:
    """``meta/info.json`` for a recorded SO-101 dataset, as LeRobot writes it."""
    motors: dict[str, type | tuple] = {f"{joint}.pos": float for joint in JOINTS}
    observation: dict[str, type | tuple] = dict(motors)
    observation |= {name: (h, w, 3) for name, (h, w) in cameras.items()}
    features = hw_to_dataset_features(observation, "observation")
    features |= hw_to_dataset_features(motors, "action")
    LeRobotDatasetMetadata.create(
        repo_id="local/pick_cube",
        fps=fps,
        features=features,
        robot_type="so101_follower",
        root=root,
        use_videos=True,
    )
    return root


def write_policy(
    path: Path,
    *,
    dataset_root: Path | None,
    cameras: dict[str, tuple[int, int]] = CAMERAS,
    device: str = "cuda",
    weights: bool = True,
    train_config: bool = True,
) -> Path:
    """A ``pretrained_model`` folder saved with LeRobot's own config savers."""
    path.mkdir(parents=True)
    inputs = {"observation.state": PolicyFeature(FeatureType.STATE, (6,))}
    inputs |= {
        f"observation.images.{name}": PolicyFeature(FeatureType.VISUAL, (3, h, w))
        for name, (h, w) in cameras.items()
    }
    policy = ACTConfig(
        device=device,
        push_to_hub=False,
        input_features=inputs,
        output_features={"action": PolicyFeature(FeatureType.ACTION, (6,))},
    )
    policy._save_pretrained(path)
    if train_config:
        dataset = DatasetConfig(
            repo_id="local/pick_cube",
            root=None if dataset_root is None else str(dataset_root),
        )
        TrainPipelineConfig(dataset=dataset, policy=policy)._save_pretrained(path)
    if weights:
        save_file({"w": torch.zeros(1)}, str(path / "model.safetensors"))
    return path


MakePolicy = Callable[..., Path]


@pytest.fixture
def make_policy(tmp_path: Path) -> MakePolicy:
    """A checkpoint at ``<tmp>/train/act_pick_cube/checkpoints/last/pretrained_model``.

    Its training dataset is at ``<tmp>/datasets/pick_cube``, recorded with
    ``dataset_cameras`` at ``dataset_fps``. ``record_dataset_root=False``
    leaves ``dataset.root`` null in train_config.json, as when training
    used ``$HF_LEROBOT_HOME/<repo_id>``.
    """

    def make(
        *,
        cameras: dict[str, tuple[int, int]] = CAMERAS,
        dataset_cameras: dict[str, tuple[int, int]] = CAMERAS,
        dataset_fps: int = 30,
        device: str = "cuda",
        weights: bool = True,
        train_config: bool = True,
        record_dataset_root: bool = True,
    ) -> Path:
        dataset_root = tmp_path / "datasets" / "pick_cube"
        if not dataset_root.exists():
            write_train_dataset(dataset_root, dataset_cameras, dataset_fps)
        path = tmp_path / "train" / "act_pick_cube" / "checkpoints" / "last"
        return write_policy(
            path / "pretrained_model",
            dataset_root=dataset_root if record_dataset_root else None,
            cameras=cameras,
            device=device,
            weights=weights,
            train_config=train_config,
        )

    return make


def _slow_line(hz: float, fps: float = 30.0) -> str:
    """A late-step warning exactly as LeRobot 0.6.1 prints it.

    Message: rollout/strategies/episodic.py L249-254, copied. Prefix: the
    ``LeRobotFormatter`` of utils/utils.py L63-72, ``%(levelname)s
    %(asctime)s %(lerobot_location)15s %(message)s``, the location being the
    last 15 characters of ``<path>:<line>``. ``fps`` is ``RolloutConfig.fps``,
    a float (rollout/configs.py L240), so it prints as ``30.0``.
    """
    return (
        "WARNING 2026-11-02 14:30:05 episodic.py:249 "
        f"Record loop is running slower ({hz:.1f} Hz) than the target FPS "
        f"({fps} Hz). Dataset frames might be dropped and robot control might "
        "be unstable. Common causes are: 1) Camera FPS not keeping up 2) Policy "
        "inference taking too long 3) CPU starvation"
    )


SlowLine = Callable[..., str]


@pytest.fixture
def slow_line() -> SlowLine:
    """``slow_line(hz, fps=30.0)``: one of LeRobot's late-step log lines."""
    return _slow_line


@pytest.fixture
def lerobot_home(tmp_path: Path) -> Path:
    """Stands in for ``$HF_LEROBOT_HOME``, outside the workspace."""
    return tmp_path / "lerobot_home"
