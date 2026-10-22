"""``so101-record``: record a local dataset with ``lerobot-record``.

The leader drives the follower exactly as in ``so101-teleop``, so the same
calibration gate runs first, also under ``--dry-run``. Then:

- ``--dataset.push_to_hub=false`` is always passed: LeRobot defaults it to
  True (lerobot 0.6.1, configs/dataset.py L43) and there is no flag here to
  change it.
- The dataset root is always passed, resolved. It defaults to LeRobot's own
  ``$HF_LEROBOT_HOME/<repo_id>`` (utils/constants.py L69,
  datasets/dataset_metadata.py L830) and is refused if it is inside the
  workspace.
- ``--dataset.no_stamp=true`` is always passed. Without it LeRobot appends a
  date-time tag to ``repo_id`` for every new dataset (configs/dataset.py
  L78-89, called at scripts/lerobot_record.py L438), so the default root would
  not be the one printed and a later ``--resume`` could not find it.
- A new dataset needs a root that does not exist: LeRobot creates it with
  ``mkdir(exist_ok=False)`` (datasets/dataset_metadata.py L832) and fails on
  any existing folder. An existing root is refused here with a hint to pass
  ``--resume``.
- ``--resume`` needs the local metadata. LeRobot's resume needs an explicit
  root (datasets/lerobot_dataset.py L854-859) and, if ``_load_metadata``
  raises ``FileNotFoundError`` or ``NotADirectoryError``, downloads ``meta/``
  for the repo_id from the Hub (datasets/dataset_metadata.py L134-148), which
  could replace local metadata with a public dataset of the same name.
  ``missing_metadata`` mirrors what ``_load_metadata`` (L214-219) reads; any
  gap is refused here. ``--episodes`` then counts the episodes to add
  (scripts/lerobot_record.py L470-471).
- A root that exists with incomplete metadata (say, after a crash) can be
  neither created nor resumed. It is named as such, with an ``mv`` command to
  set it aside; nothing is deleted.
- A new dataset whose name starts with ``eval_`` is refused, as LeRobot does
  when it creates one (scripts/lerobot_record.py L431-436). Resume has no
  such check there, so an ``eval_`` dataset can be resumed.
"""

import argparse
import json
import re
import shlex
import subprocess
import sys
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path

from hw_setup.lerobot_argv import format_command, record_argv
from hw_setup.teleop import calibration_problems
from hw_setup.workspace import WorkspaceError, find_workspace_root, load_local_config

PROG = "so101-record"
INFO_FILE = Path("meta") / "info.json"
TASKS_FILE = Path("meta") / "tasks.parquet"
EPISODES_DIR = Path("meta") / "episodes"
EVAL_PREFIX = "eval_"
_REPO_ID = re.compile(r"[^/\s]+/[^/\s]+")

Runner = Callable[[list[str]], int]


def _run(argv: list[str]) -> int:
    return subprocess.run(argv, check=False).returncode


def default_lerobot_home() -> Path:
    """LeRobot's ``HF_LEROBOT_HOME`` (imported late: it pulls in torch)."""
    from lerobot.utils.constants import HF_LEROBOT_HOME

    return HF_LEROBOT_HOME


def _task(text: str) -> str:
    if not text.strip():
        raise argparse.ArgumentTypeError("task text must not be empty")
    return text


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


def _positive_float(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a number: {text!r}") from None
    if value <= 0:
        raise argparse.ArgumentTypeError(f"must be more than 0, got {value}")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description=(
            "Record a local LeRobot dataset, the leader driving the follower. "
            "Never pushes to the Hugging Face Hub."
        ),
    )
    parser.add_argument(
        "--task", required=True, type=_task, help="what the episodes show"
    )
    parser.add_argument(
        "--repo-id", required=True, type=_repo_id, help="dataset name, USER/NAME"
    )
    parser.add_argument(
        "--episodes", required=True, type=_positive_int, help="episodes to record"
    )
    parser.add_argument(
        "--dataset-root",
        type=Path,
        help="where to write it, outside the workspace "
        "(default: $HF_LEROBOT_HOME/USER/NAME)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="add episodes to the existing dataset at the dataset root",
    )
    parser.add_argument("--episode-time-s", type=_positive_float)
    parser.add_argument("--reset-time-s", type=_positive_float)
    parser.add_argument("--fps", type=_positive_int)
    parser.add_argument(
        "--cameras",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="record the configured cameras (default: on)",
    )
    parser.add_argument(
        "--display", action="store_true", help="show the data live (--display_data)"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="run the checks, print the command"
    )
    parser.add_argument(
        "--config", type=Path, help="machine config (default: configs/local.yaml)"
    )
    return parser


def missing_metadata(dataset_root: Path) -> list[str]:
    """The metadata files LeRobot needs to load a local dataset, if missing.

    Mirrors ``LeRobotDatasetMetadata._load_metadata`` (lerobot 0.6.1,
    datasets/dataset_metadata.py L214-219): ``meta/info.json`` always,
    ``meta/tasks.parquet`` when info counts tasks, and at least one
    ``meta/episodes/*/*.parquet`` when it counts episodes
    (datasets/io_utils.py L75-77). ``meta/stats.json`` is optional (L172).
    An unreadable info.json also counts: nothing else can be checked.
    """
    info_path = dataset_root / INFO_FILE
    if not info_path.is_file():
        return [str(INFO_FILE)]
    try:
        info = json.loads(info_path.read_text())
        total_tasks = int(info.get("total_tasks", 0))
        total_episodes = int(info.get("total_episodes", 0))
    except (OSError, ValueError, TypeError, AttributeError) as err:
        return [f"{INFO_FILE} (unreadable: {err})"]
    missing = []
    if total_tasks > 0 and not (dataset_root / TASKS_FILE).is_file():
        missing.append(str(TASKS_FILE))
    episodes = dataset_root / EPISODES_DIR
    if total_episodes > 0 and not any(episodes.glob("*/*.parquet")):
        missing.append(f"{EPISODES_DIR}/*/*.parquet")
    return missing


def set_aside_command(dataset_root: Path, now: datetime | None = None) -> str:
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    aside = dataset_root.with_name(f"{dataset_root.name}.broken-{stamp}")
    return shlex.join(["mv", str(dataset_root), str(aside)])


def dataset_root_problem(dataset_root: Path, workspace: Path, resume: bool) -> str:
    """Why ``dataset_root`` (already resolved) cannot be used, or ''."""
    if dataset_root.is_relative_to(workspace.resolve()):
        return (
            f"dataset root {dataset_root} is inside the workspace "
            f"{workspace.resolve()}; pass --dataset-root outside it"
        )
    if not dataset_root.exists():
        if resume:
            return (
                f"nothing to resume: {dataset_root} does not exist. "
                "Drop --resume to start a new dataset."
            )
        return ""
    missing = missing_metadata(dataset_root)
    if missing:
        return (
            f"{dataset_root} holds an incomplete dataset (missing: "
            f"{', '.join(missing)}). LeRobot can neither create a dataset there "
            "nor resume it without fetching metadata from the Hub. Set it aside "
            f"and start again:\n  {set_aside_command(dataset_root)}"
        )
    if not resume:
        return (
            f"dataset root {dataset_root} already exists. Pass --resume to add "
            "episodes to it, or choose another --repo-id or --dataset-root."
        )
    return ""


def main(
    argv: Sequence[str] | None = None,
    *,
    runner: Runner = _run,
    root: Path | None = None,
    lerobot_home: Path | None = None,
) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if not args.resume and args.repo_id.split("/", 1)[1].startswith(EVAL_PREFIX):
        parser.error(
            f"--repo-id: names starting with {EVAL_PREFIX!r} are reserved by "
            "LeRobot for policy evaluation; choose another name"
        )
    try:
        workspace = root if root is not None else find_workspace_root()
        config = load_local_config(workspace, args.config)
        problems = calibration_problems(config, workspace)
        if problems:
            for problem in problems:
                print(f"{PROG}: refusing to run: {problem}", file=sys.stderr)
            return 1
        if args.dataset_root is not None:
            dataset_root = args.dataset_root.expanduser().resolve()
        else:
            home = lerobot_home if lerobot_home is not None else default_lerobot_home()
            dataset_root = (home / args.repo_id).resolve()
        problem = dataset_root_problem(dataset_root, workspace, args.resume)
        if problem:
            print(f"{PROG}: refusing to run: {problem}", file=sys.stderr)
            return 1
        command = record_argv(
            config,
            workspace,
            repo_id=args.repo_id,
            single_task=args.task,
            num_episodes=args.episodes,
            dataset_root=dataset_root,
            episode_time_s=args.episode_time_s,
            reset_time_s=args.reset_time_s,
            fps=args.fps,
            push_to_hub=False,
            no_stamp=True,
            cameras=args.cameras,
            display_data=args.display,
            resume=args.resume,
        )
    except (WorkspaceError, ValueError) as err:
        print(f"{PROG}: {err}", file=sys.stderr)
        return 1

    mode = "resume, adding episodes" if args.resume else "new dataset"
    print("Calibration checked: leader and follower pass.")
    print(f"Dataset: {args.repo_id} ({mode})")
    print(f"Dataset root: {dataset_root}")
    print(f"Task: {args.task}")
    print(f"Episodes: {args.episodes}")
    print("Push to Hub: no")
    print(f"Command: {format_command(command)}")
    if args.dry_run:
        print("Dry run: nothing was run.")
        return 0
    return runner(command)


def cli() -> None:
    sys.exit(main())
