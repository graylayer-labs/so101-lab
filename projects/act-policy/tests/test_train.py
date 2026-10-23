"""Tests for so101-train. Tmp workspaces and a tiny local dataset; no Hub."""

import json
import re
import shlex
import shutil
import socket
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import draccus
import numpy as np
import pytest
from lerobot.configs import parser
from lerobot.configs.train import TrainPipelineConfig
from lerobot.policies.act.configuration_act import ACTConfig
from lerobot.scripts import lerobot_rollout

from act_policy import evaluate, train
from act_policy.evaluate import RunResult
from act_policy.policy_check import load_policy
from act_policy.train import (
    DATASET_RECORD,
    DEFAULT_RUN_CONFIG,
    LEROBOT_DIR,
    RunConfigError,
    TrainSettings,
    load_run_config,
    main,
    pick_device,
    read_dataset_record,
    run_name,
    train_argv,
)
from hw_setup.lerobot_argv import format_command

JOINTS = ["shoulder_pan", "elbow_flex", "gripper"]
CAMERA = "observation.images.front"
FPS = 10
EPISODES = 2
FRAMES_PER_EPISODE = 8


def write_tiny_dataset(root: Path) -> Path:
    """A real LeRobot v3.0 dataset, written with LeRobot's own writers.

    Two episodes of eight frames at 10 fps: a 3-joint state and action and
    one 32x32 camera stored as images (no video encoding, so no ffmpeg).
    """
    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    features = {
        "observation.state": {"dtype": "float32", "shape": (3,), "names": JOINTS},
        "action": {"dtype": "float32", "shape": (3,), "names": JOINTS},
        CAMERA: {
            "dtype": "image",
            "shape": (32, 32, 3),
            "names": ["height", "width", "channels"],
        },
    }
    dataset = LeRobotDataset.create(
        "local/tiny",
        fps=FPS,
        features=features,
        root=root,
        robot_type="so_follower",
        use_videos=False,
    )
    rng = np.random.default_rng(0)
    for _ in range(EPISODES):
        for _ in range(FRAMES_PER_EPISODE):
            dataset.add_frame(
                {
                    "observation.state": rng.random(3, dtype=np.float32),
                    "action": rng.random(3, dtype=np.float32),
                    CAMERA: rng.integers(0, 255, (32, 32, 3), dtype=np.uint8),
                    "task": "pick",
                }
            )
        dataset.save_episode()
    dataset.finalize()
    return root


@pytest.fixture(scope="session")
def tiny_dataset_source(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return write_tiny_dataset(tmp_path_factory.mktemp("source") / "tiny")


CopyDataset = Callable[[Path], Path]


@pytest.fixture
def copy_dataset(tiny_dataset_source: Path) -> CopyDataset:
    """Copy the session's tiny dataset to ``target`` and return it."""

    def copy(target: Path) -> Path:
        shutil.copytree(tiny_dataset_source, target)
        return target

    return copy


NOW = datetime(2026, 10, 23, 14, 5, 9, tzinfo=UTC)
STAMP = "20261023T140509Z"
SETTINGS = TrainSettings(steps=100_000, batch_size=8, save_freq=10_000, log_freq=200)


def lerobot_default(name: str) -> object:
    return TrainPipelineConfig.__dataclass_fields__[name].default


# --- device ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("available", "expected"),
    [
        ({"cuda", "mps", "cpu"}, "cuda"),
        ({"mps", "cpu"}, "mps"),
        ({"cpu"}, "cpu"),
    ],
)
def test_device_is_cuda_then_mps_then_cpu(available: set[str], expected: str) -> None:
    assert pick_device(lambda device: device in available) == expected


# --- run name -------------------------------------------------------------


def test_run_name_is_the_utc_time_and_the_dataset_name() -> None:
    assert run_name("local/so101_pick_cube", NOW) == f"{STAMP}_so101_pick_cube"


def test_run_name_converts_to_utc() -> None:
    local = NOW.astimezone(timezone(timedelta(hours=2)))
    assert run_name("local/so101_pick_cube", local).startswith(STAMP)


# --- argv -----------------------------------------------------------------


def argv(device: str = "mps", **kwargs: object) -> list[str]:
    options: dict = {
        "repo_id": "local/cube",
        "dataset_root": Path("/data/cube"),
        "output_dir": Path("/ws/outputs/train/run/lerobot"),
        "device": device,
        "settings": SETTINGS,
        "job_name": "act_pick_cube",
        **kwargs,
    }
    return train_argv(**options)


def test_train_snapshot() -> None:
    assert argv() == [
        "lerobot-train",
        "--policy.type=act",
        "--dataset.repo_id=local/cube",
        "--dataset.root=/data/cube",
        "--policy.device=mps",
        "--policy.push_to_hub=false",
        "--wandb.enable=false",
        "--steps=100000",
        "--batch_size=8",
        "--save_freq=10000",
        "--log_freq=200",
        "--output_dir=/ws/outputs/train/run/lerobot",
        "--job_name=act_pick_cube",
    ]


def test_cuda_turns_amp_on() -> None:
    assert "--policy.use_amp=true" in argv("cuda")
    assert not any("use_amp" in arg for arg in argv("mps"))
    assert not any("use_amp" in arg for arg in argv("cpu"))


def test_relative_paths_are_refused() -> None:
    with pytest.raises(ValueError, match="absolute"):
        argv(dataset_root=Path("data/cube"))
    with pytest.raises(ValueError, match="absolute"):
        argv(output_dir=Path("outputs/train/run"))


# --- through LeRobot's own parser ----------------------------------------


def parse(args: list[str]) -> TrainPipelineConfig:
    """Parse as lerobot-train does (scripts/lerobot_train.py L211 parser.wrap)."""
    return draccus.parse(config_class=TrainPipelineConfig, args=args[1:])


def test_lerobot_parses_the_command(tmp_path: Path) -> None:
    output_dir = tmp_path / "run" / "lerobot"
    cfg = parse(argv("cpu", output_dir=output_dir))
    assert isinstance(cfg.policy, ACTConfig)
    assert cfg.policy.device == "cpu"
    assert cfg.policy.push_to_hub is False
    assert cfg.policy.use_amp is False
    assert cfg.wandb.enable is False
    assert cfg.dataset.repo_id == "local/cube"
    assert cfg.dataset.root == "/data/cube"
    assert (cfg.steps, cfg.batch_size) == (100_000, 8)
    assert (cfg.save_freq, cfg.log_freq) == (10_000, 200)
    assert cfg.output_dir == output_dir
    assert cfg.job_name == "act_pick_cube"
    cfg.validate()  # what lerobot-train runs before training (train.py L226)


def test_lerobot_parses_amp_on_cuda(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Pretend CUDA is here, or LeRobot would swap the device and, on mps,
    # turn AMP off (configs/policies.py L86-96). Parsing touches no GPU.
    import torch

    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    cfg = parse(argv("cuda", output_dir=tmp_path / "out"))
    assert cfg.policy is not None
    assert cfg.policy.device == "cuda"
    assert cfg.policy.use_amp is True


def test_lerobot_would_push_without_the_flag(tmp_path: Path) -> None:
    """Why push_to_hub=false is always passed: the default fails at start."""
    args = [
        a for a in argv("cpu", output_dir=tmp_path / "out") if "push_to_hub" not in a
    ]
    cfg = parse(args)
    assert cfg.policy is not None and cfg.policy.push_to_hub is True
    with pytest.raises(ValueError, match="repo_id"):
        cfg.validate()


def test_lerobot_refuses_an_existing_output_dir(tmp_path: Path) -> None:
    """Why the LeRobot folder is left for lerobot-train to make (train.py L259)."""
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    with pytest.raises(FileExistsError):
        parse(argv("cpu", output_dir=output_dir)).validate()


def test_lerobot_rejects_an_unknown_flag() -> None:
    """Guards the parse tests: draccus must fail on a misspelt flag."""
    with pytest.raises(SystemExit):
        parse([*argv("cpu"), "--policy.push_to_hubb=false"])


def test_default_steps_and_batch_are_lerobots() -> None:
    config = load_run_config(DEFAULT_RUN_CONFIG)
    assert config.train.steps == lerobot_default("steps") == 100_000
    assert config.train.batch_size == lerobot_default("batch_size") == 8


# --- run config -----------------------------------------------------------


def test_default_run_config() -> None:
    config = load_run_config(DEFAULT_RUN_CONFIG)
    assert config.job_name == "act_pick_cube"
    assert config.train == TrainSettings(
        steps=100_000, batch_size=8, save_freq=10_000, log_freq=200
    )
    assert config.smoke == TrainSettings(
        steps=1_000, batch_size=8, save_freq=1_000, log_freq=50
    )


@pytest.mark.parametrize(
    "text",
    [
        "job_name: x\ntrain: {steps: 1, batch_size: 1, save_freq: 1, log_freq: 1}\n",
        "job_name: x\ntrain: {steps: 0, batch_size: 1, save_freq: 1, log_freq: 1}\n"
        "smoke: {steps: 1, batch_size: 1, save_freq: 1, log_freq: 1}\n",
        "job_name: x\ntrain: {steps: 1, batch_size: 1, save_freq: 1}\n"
        "smoke: {steps: 1, batch_size: 1, save_freq: 1, log_freq: 1}\n",
        "job_name: ''\ntrain: {steps: 1, batch_size: 1, save_freq: 1, log_freq: 1}\n"
        "smoke: {steps: 1, batch_size: 1, save_freq: 1, log_freq: 1}\n",
        "- not a mapping\n",
    ],
)
def test_bad_run_config_is_refused(tmp_path: Path, text: str) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text(text)
    with pytest.raises(RunConfigError):
        load_run_config(path)


# --- dataset record -------------------------------------------------------


def test_dataset_record_is_read_from_local_files(
    tmp_path: Path, copy_dataset: CopyDataset
) -> None:
    root = copy_dataset(tmp_path / "local" / "tiny")
    record = read_dataset_record("local/tiny", root)
    assert record["repo_id"] == "local/tiny"
    assert record["root"] == str(root)
    assert record["total_episodes"] == EPISODES
    assert record["fps"] == FPS
    assert list(record["cameras"]) == [CAMERA]
    assert record["cameras"][CAMERA]["shape"] == [32, 32, 3]
    json.dumps(record)


def test_dataset_record_names_the_video_decode_backend(
    tmp_path: Path, copy_dataset: CopyDataset
) -> None:
    from lerobot.utils.import_utils import get_safe_default_video_backend

    root = copy_dataset(tmp_path / "local" / "tiny")
    record = read_dataset_record("local/tiny", root)
    assert record["decode_backend"] == get_safe_default_video_backend()
    assert record["decode_backend"] in ("pyav", "torchcodec")


def test_lerobot_train_runs_with_the_hub_offline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With meta/ complete but data/ missing, lerobot-train would still try
    the Hub (datasets/lerobot_dataset.py L272-278, L643-675)."""
    seen: dict = {}

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        seen.update(kwargs)
        return subprocess.CompletedProcess(argv, 5)

    monkeypatch.setenv("SO101_TEST_MARKER", "kept")
    monkeypatch.setattr(train.subprocess, "run", fake_run)
    assert train._run(["lerobot-train"]) == 5
    env = seen["env"]
    assert isinstance(env, dict)
    assert env["HF_HUB_OFFLINE"] == "1"
    assert env["SO101_TEST_MARKER"] == "kept"


def test_the_network_guard_works() -> None:
    with pytest.raises(AssertionError, match="network"):
        socket.create_connection(("huggingface.co", 443))


# --- so101-train ----------------------------------------------------------


class Runner:
    def __init__(self, code: int = 0) -> None:
        self.calls: list[list[str]] = []
        self.code = code
        self.seen_output_dir_existed: list[bool] = []

    def __call__(self, argv: list[str]) -> int:
        self.calls.append(argv)
        output_dir = Path(option(argv, "--output_dir"))
        self.seen_output_dir_existed.append(output_dir.exists())
        return self.code


def option(argv: list[str], name: str) -> str:
    (value,) = [a.split("=", 1)[1] for a in argv if a.startswith(f"{name}=")]
    return value


@pytest.fixture
def root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    workspace = tmp_path_factory.mktemp("workspace")
    (workspace / "hardware" / "calibration").mkdir(parents=True)
    return workspace


@pytest.fixture
def home(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Stands in for $HF_LEROBOT_HOME, outside the workspace."""
    return tmp_path_factory.mktemp("lerobot-home")


@pytest.fixture
def dataset(home: Path, copy_dataset: CopyDataset) -> Path:
    return copy_dataset(home / "local" / "cube")


BASE = ["--repo-id", "local/cube"]


def run(
    args: list[str],
    root: Path,
    home: Path,
    runner: Runner | None = None,
    available: set[str] | None = None,
) -> int:
    devices = available if available is not None else {"mps", "cpu"}
    return main(
        args,
        runner=runner or Runner(),
        root=root,
        lerobot_home=home,
        now=NOW,
        device_available=lambda device: device in devices,
    )


def run_dir(root: Path) -> Path:
    return root / "outputs" / "train" / f"{STAMP}_cube"


def test_default_run(root: Path, home: Path, dataset: Path) -> None:
    runner = Runner()
    assert run(BASE, root, home, runner) == 0
    assert runner.calls == [
        train_argv(
            repo_id="local/cube",
            dataset_root=dataset.resolve(),
            output_dir=run_dir(root).resolve() / LEROBOT_DIR,
            device="mps",
            settings=SETTINGS,
            job_name="act_pick_cube",
        )
    ]
    # lerobot-train must be the one to create its own folder (train.py L259).
    assert runner.seen_output_dir_existed == [False]


def test_runner_exit_code_is_returned(root: Path, home: Path, dataset: Path) -> None:
    assert run(BASE, root, home, Runner(code=3)) == 3


def test_dataset_record_is_written_before_training(
    root: Path, home: Path, dataset: Path
) -> None:
    def runner(argv: list[str]) -> int:
        record = json.loads((run_dir(root) / DATASET_RECORD).read_text())
        assert record["repo_id"] == "local/cube"
        assert record["root"] == str(dataset.resolve())
        assert record["total_episodes"] == EPISODES
        assert record["fps"] == FPS
        assert CAMERA in record["cameras"]
        return 0

    assert (
        main(
            BASE,
            runner=runner,
            root=root,
            lerobot_home=home,
            now=NOW,
            device_available=lambda d: d == "cpu",
        )
        == 0
    )


def test_smoke_is_short(root: Path, home: Path, dataset: Path) -> None:
    runner = Runner()
    run([*BASE, "--smoke"], root, home, runner)
    command = runner.calls[0]
    assert option(command, "--steps") == "1000"
    assert option(command, "--save_freq") == "1000"
    assert option(command, "--log_freq") == "50"


def test_steps_and_batch_size_override(root: Path, home: Path, dataset: Path) -> None:
    runner = Runner()
    run([*BASE, "--smoke", "--steps", "500", "--batch-size", "4"], root, home, runner)
    command = runner.calls[0]
    assert option(command, "--steps") == "500"
    assert option(command, "--batch_size") == "4"
    # A save_freq past the end means only the final checkpoint.
    assert option(command, "--save_freq") == "500"


@pytest.mark.parametrize("value", ["0", "-1", "x"])
def test_steps_must_be_positive(
    root: Path, home: Path, dataset: Path, value: str
) -> None:
    with pytest.raises(SystemExit):
        run([*BASE, "--steps", value], root, home)


def test_device_is_auto_picked(root: Path, home: Path, dataset: Path) -> None:
    runner = Runner()
    run(BASE, root, home, runner, available={"cuda", "mps", "cpu"})
    assert option(runner.calls[0], "--policy.device") == "cuda"
    assert "--policy.use_amp=true" in runner.calls[0]


def test_an_unavailable_device_is_refused(
    root: Path, home: Path, dataset: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """LeRobot would fall back silently (configs/policies.py L86-89)."""
    runner = Runner()
    assert run([*BASE, "--device", "cuda"], root, home, runner) == 1
    assert runner.calls == []
    assert "cuda is not available" in capsys.readouterr().err


def test_explicit_device(root: Path, home: Path, dataset: Path) -> None:
    runner = Runner()
    run([*BASE, "--device", "cpu"], root, home, runner)
    assert option(runner.calls[0], "--policy.device") == "cpu"


def test_explicit_dataset_root(
    root: Path, tmp_path: Path, home: Path, copy_dataset: CopyDataset
) -> None:
    elsewhere = copy_dataset(tmp_path / "elsewhere")
    runner = Runner()
    assert run([*BASE, "--dataset-root", str(elsewhere)], root, home, runner) == 0
    assert option(runner.calls[0], "--dataset.root") == str(elsewhere.resolve())


def test_missing_dataset_is_refused(
    root: Path, home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = Runner()
    assert run(BASE, root, home, runner) == 1
    assert runner.calls == []
    assert "no dataset" in capsys.readouterr().err
    assert not (root / "outputs").exists()


@pytest.mark.parametrize(
    "part", ["meta/info.json", "meta/tasks.parquet", "meta/episodes"]
)
def test_incomplete_metadata_is_refused_not_fetched(
    root: Path, home: Path, dataset: Path, part: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """LeRobot would pull meta/ from the Hub (datasets/dataset_metadata.py L140-148)."""
    target = dataset / part
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()
    runner = Runner()
    assert run(BASE, root, home, runner) == 1
    assert runner.calls == []
    assert "incomplete" in capsys.readouterr().err


def test_an_existing_run_dir_is_refused(
    root: Path, home: Path, dataset: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_dir(root).mkdir(parents=True)
    runner = Runner()
    assert run(BASE, root, home, runner) == 1
    assert runner.calls == []
    assert "already exists" in capsys.readouterr().err


def test_repo_id_must_be_user_slash_name(root: Path, home: Path) -> None:
    with pytest.raises(SystemExit):
        run(["--repo-id", "cube"], root, home)


def test_dry_run_prints_the_plan_and_runs_nothing(
    root: Path, home: Path, dataset: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = Runner()
    assert run([*BASE, "--dry-run"], root, home, runner) == 0
    assert runner.calls == []
    out = capsys.readouterr().out
    expected = train_argv(
        repo_id="local/cube",
        dataset_root=dataset.resolve(),
        output_dir=run_dir(root).resolve() / LEROBOT_DIR,
        device="mps",
        settings=SETTINGS,
        job_name="act_pick_cube",
    )
    assert f"Command: {format_command(expected)}" in out
    assert f"Episodes: {EPISODES}" in out
    assert f"FPS: {FPS}" in out
    assert CAMERA in out
    assert "Device: mps" in out
    assert "Push to Hub: no" in out
    assert "Dry run: nothing was run." in out
    assert not (root / "outputs").exists()


def test_explicit_run_config(
    root: Path, home: Path, dataset: Path, tmp_path: Path
) -> None:
    path = tmp_path / "run.yaml"
    path.write_text(
        "job_name: other\n"
        "train: {steps: 7, batch_size: 2, save_freq: 7, log_freq: 1}\n"
        "smoke: {steps: 3, batch_size: 2, save_freq: 3, log_freq: 1}\n"
    )
    runner = Runner()
    assert run([*BASE, "--config", str(path)], root, home, runner) == 0
    assert option(runner.calls[0], "--steps") == "7"
    assert option(runner.calls[0], "--job_name") == "other"


def test_default_lerobot_home_is_lerobots_own(
    root: Path, home: Path, dataset: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import lerobot.utils.constants

    monkeypatch.setattr(lerobot.utils.constants, "HF_LEROBOT_HOME", home)
    runner = Runner()
    assert (
        main(
            BASE,
            runner=runner,
            root=root,
            now=NOW,
            device_available=lambda d: d == "cpu",
        )
        == 0
    )
    assert option(runner.calls[0], "--dataset.root") == str(dataset.resolve())


# --- a real lerobot-train, on CPU ----------------------------------------

# A tiny ACT so a few steps take seconds: no pretrained backbone (that would
# download ResNet-18 weights), short chunks, a small transformer.
TINY_ACT = [
    "--policy.pretrained_backbone_weights=null",
    "--policy.chunk_size=4",
    "--policy.n_action_steps=4",
    "--policy.dim_model=32",
    "--policy.dim_feedforward=64",
    "--policy.n_heads=2",
    "--policy.n_encoder_layers=1",
    "--policy.latent_dim=4",
    "--num_workers=0",
]


def micro_train(root: Path, home: Path, tmp_path: Path) -> tuple[int, list[str]]:
    """so101-train running lerobot-train for 4 steps on CPU, offline.

    Returns the exit code and each lerobot-train run's output.
    """
    config = tmp_path / "micro.yaml"
    config.write_text(
        "job_name: micro\n"
        "train: {steps: 4, batch_size: 2, save_freq: 4, log_freq: 1}\n"
        "smoke: {steps: 4, batch_size: 2, save_freq: 4, log_freq: 1}\n"
    )
    bin_dir = Path(sys.executable).parent
    env = {"PATH": str(bin_dir), "HF_HUB_OFFLINE": "1", "HOME": str(tmp_path)}
    env["HF_LEROBOT_HOME"] = str(home)
    logs: list[str] = []

    def runner(argv: list[str]) -> int:
        done = subprocess.run(
            [str(bin_dir / argv[0]), *argv[1:], *TINY_ACT],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        logs.append(done.stdout + done.stderr)
        return done.returncode

    code = main(
        [*BASE, "--config", str(config), "--device", "cpu"],
        runner=runner,
        root=root,
        lerobot_home=home,
        now=NOW,
        device_available=lambda d: d == "cpu",
    )
    return code, logs


def test_a_real_cpu_micro_train(
    root: Path, home: Path, dataset: Path, tmp_path: Path
) -> None:
    """Runs lerobot-train for 4 steps on CPU (about 3 s on an M4), offline."""
    code, logs = micro_train(root, home, tmp_path)
    assert code == 0, logs[-1][-3000:]
    checkpoint = run_dir(root) / LEROBOT_DIR / "checkpoints" / "last"
    assert (checkpoint / "pretrained_model" / "model.safetensors").is_file()
    assert (run_dir(root) / DATASET_RECORD).is_file()
    losses = re.findall(r"step:\d+ .*? loss:([0-9.]+)", logs[-1])
    assert len(losses) == 4


# --- the trained checkpoint through so101-eval's preflight ----------------

REPO = Path(__file__).parents[3]


def eval_workspace(root: Path) -> None:
    """Add what so101-eval needs to ``root``: the follower's calibration and a
    local.yaml whose one camera is the tiny dataset's (front, 32x32, 10 fps).
    """
    follower = root / "hardware" / "calibration" / "follower"
    follower.mkdir(parents=True)
    shutil.copy(REPO / "hardware" / "calibration" / "follower" / "main.json", follower)
    (root / "configs").mkdir()
    (root / "configs" / "local.yaml").write_text(
        "arms:\n"
        "  leader: {id: main, port: /dev/cu.usbmodem0000000001}\n"
        "  follower: {id: main, port: /dev/cu.usbmodem0000000002}\n"
        "cameras:\n"
        f"  front: {{index: 0, width: 32, height: 32, fps: {FPS}}}\n"
    )


def test_a_micro_trained_checkpoint_passes_the_eval_preflight(
    root: Path,
    home: Path,
    dataset: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real 4-step checkpoint through policy_check and so101-eval --dry-run."""
    code, logs = micro_train(root, home, tmp_path)
    assert code == 0, logs[-1][-3000:]
    checkpoint = run_dir(root) / LEROBOT_DIR / "checkpoints" / "last"
    pretrained = checkpoint / "pretrained_model"

    policy = load_policy(pretrained, lerobot_home=home)
    assert policy.policy_type == "act"
    assert policy.cameras == {"front": (32, 32)}
    assert policy.dataset_root.resolve() == dataset.resolve()
    assert policy.dataset_fps == FPS
    assert policy.dataset_cameras == {"front": (32, 32, FPS)}
    assert policy.n_action_steps == 4  # TINY_ACT's, read back from config.json

    eval_workspace(root)
    capsys.readouterr()

    def no_run(argv: list[str]) -> RunResult:
        raise AssertionError("--dry-run ran a command")

    def no_input(prompt: str = "") -> str:
        raise AssertionError("--dry-run asked a question")

    args = ["--policy", str(pretrained), "--task", "pick", "--episodes", "1"]
    assert (
        evaluate.main(
            [*args, "--device", "cpu", "--dry-run"],
            runner=no_run,
            root=root,
            lerobot_home=home,
            ask=no_input,
            available_devices=lambda: {"cpu"},
        )
        == 0
    )
    out = capsys.readouterr().out
    assert f"Cameras checked: front 32x32 at {FPS} fps match" in out
    assert f"Dataset: local/rollout_{STAMP}_cube_last (new dataset)" in out
    assert "Dry run: nothing was run." in out

    # LeRobot's own rollout parser loads the real checkpoint from the command.
    command = shlex.split(out.split("Command: ", 1)[1].splitlines()[0])
    monkeypatch.setattr(sys, "argv", command)
    cli_args = parser.filter_path_args(["policy"], command[1:])
    cfg = draccus.parse(config_class=lerobot_rollout.RolloutConfig, args=cli_args)
    assert isinstance(cfg.policy, ACTConfig)
    assert cfg.policy.n_action_steps == 4
    assert cfg.device == "cpu"
    assert cfg.fps == FPS
