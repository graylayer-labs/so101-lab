"""``so101-eval``: run a trained policy on the follower and score each trial.

Each trial is one ``lerobot-rollout --strategy.type=episodic`` run of one
episode (``act_policy.rollout_argv``); the owner scores it at a prompt when
it ends and the score is appended to ``outputs/eval/<run>/<checkpoint>/trials.jsonl``
(``act_policy.trials``). The first trial creates the eval dataset and later
ones resume it, so every episode's video ends up in one local dataset.

Before anything runs, also under ``--dry-run``:

- the follower's calibration passes (``hw_setup.teleop.calibration_problems``
  for the follower only: no leader is used, see ``act_policy.rollout_argv``);
- the policy folder holds a LeRobot checkpoint and its training dataset's
  metadata can be read (``act_policy.policy_check.load_policy``);
- the cameras in ``configs/local.yaml`` match the policy and the training
  dataset in name, size and fps (``camera_problems``);
- the device is available (``auto``: cuda, then mps, then cpu); on mps the
  control-rate risk is printed;
- the dataset root follows ``so101-record``'s rules
  (``hw_setup.record.dataset_root_problem``): outside the workspace, new
  unless ``--resume``, and never a half-written one. The default is
  ``$HF_LEROBOT_HOME/local/rollout_<run>_<checkpoint>``.

The follower's start pose is not checked: no safe pose is defined in the
repo and the leader is not connected to compare with. Each trial is its own
process, and LeRobot disables torque when it disconnects
(``disable_torque_on_disconnect=True``, robots/so_follower/
config_so_follower.py L31; so_follower.py L233-234), so the arm goes limp
after every trial and the next one starts from wherever it came to rest.
LeRobot captures the pose at startup and drives the follower back to it at the end (see
``act_policy.rollout_argv``), so each trial asks for ``y`` to confirm the
follower is at its rest pose before it starts.

``--dataset.push_to_hub=false`` is always passed and the movement cap
(``--max-step``, default ``hw_setup.teleop.DEFAULT_MAX_STEP``) always named.
``--dry-run`` prints the plan and the exact command, and runs nothing.

The rollout's output is teed: shown on the terminal as it comes and kept,
per trial, in ``outputs/eval/<run>/<checkpoint>/logs/trial-<n>.log``. From it and the
episode's frame count, ``act_policy.control_rate`` measures the control
rate, which goes into trials.jsonl; below 25 Hz a warning is printed, as
#76 asks for the rate to be noted with the result.
"""

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any

from act_policy.control_rate import LOW_HZ, ControlRate, measure
from act_policy.policy_check import (
    Policy,
    PolicyError,
    available_devices,
    camera_problems,
    eval_dataset_problems,
    load_policy,
    run_name,
    select_device,
)
from act_policy.rollout_argv import ROLLOUT_PREFIX, rollout_argv
from act_policy.trials import (
    Ask,
    append_trial,
    ask_score,
    count_trials,
    trial_record,
    trials_path,
)
from hw_setup.lerobot_argv import format_command
from hw_setup.record import (
    INFO_FILE,
    dataset_root_problem,
    default_lerobot_home,
)
from hw_setup.teleop import (
    add_max_step_argument,
    calibration_problems,
    describe_max_step,
)
from hw_setup.workspace import WorkspaceError, find_workspace_root, load_local_config
from so101.arm import ArmRole

PROG = "so101-eval"
REPO_OWNER = "local"
_REPO_ID = re.compile(r"[^/\s]+/[^/\s]+")

LOGS_DIR = "logs"


@dataclass(frozen=True)
class RunResult:
    code: int
    lines: list[str]  # stdout and stderr, merged, without line endings
    interrupted: bool = False  # Ctrl-C during the run


SHUTDOWN_LOG = "Shutdown signal"  # LeRobot's log on a signal, utils/process.py L89
SHUTDOWN_GRACE_S = 1.0
STOP_WAIT_S = 60.0
PROTOCOL_EPISODE_TIME_S = 30.0  # "a time limit of 30 s" (#76 eval protocol)
INTERRUPTED = 130  # the shell's exit status for Ctrl-C


Runner = Callable[[list[str]], RunResult]

# so_follower.py L221-226: with max_relative_target set, every send_action
# first reads Present_Position ("Slower fps expected").
CAP_COST_NOTE = (
    "The movement cap (--max-step) also costs rate: it adds a bus read of the "
    "follower's position on every step. It is a safety limit, so keep it, but "
    "say it was on when you compare rates."
)
MPS_WARNING = (
    "WARNING: running the policy on mps. A published SO-101 ACT eval measured "
    "about 15 Hz on an Apple M4 with mps and 40% success, against 30 Hz and "
    "90% on CUDA for the same checkpoint. LeRobot logs 'Record loop is running "
    "slower' whenever a step misses the target fps. If the loop runs below "
    "about 25 Hz, write the rate down with the trials and rerun one diagnostic "
    f"with --device cpu or without --display. {CAP_COST_NOTE}"
)
CPU_WARNING = "WARNING: running the policy on cpu; expect a slow control loop."
START_POSE_WARNING = (
    "WARNING: the follower's start pose is not checked. LeRobot records the "
    "pose the follower is in when it connects and drives it back there after "
    "each trial, so put it at its rest pose (the pose the training episodes "
    "started from) before you type y. At the end of every trial the follower "
    "loses torque and goes limp (LeRobot disconnects with "
    "disable_torque_on_disconnect=True): support the arm or let it come to "
    "rest in a safe pose before each trial ends, and use a rest pose that "
    "holds without power."
)


def _wait(proc: subprocess.Popen[str], timeout: float) -> bool:
    """Wait for ``proc`` to exit, up to ``timeout`` s; True if it did.

    A further Ctrl-C while waiting is noted and the wait goes on: the child
    gets it from the terminal too, and stopping here would leave the arm
    moving behind a shell prompt.
    """
    deadline = time.monotonic() + timeout
    while True:
        left = deadline - time.monotonic()
        if left <= 0:
            return proc.poll() is not None
        try:
            proc.wait(timeout=left)
            return True
        except subprocess.TimeoutExpired:
            return False
        except KeyboardInterrupt:
            print(
                f"\n{PROG}: Ctrl-C again: LeRobot force-exits on a second signal "
                "(utils/process.py L97-99); still waiting for it to exit.",
                file=sys.stderr,
            )


def _stop_after_ctrl_c(proc: subprocess.Popen[str], lines: list[str]) -> None:
    """Let LeRobot finish its own clean shutdown after a Ctrl-C.

    A terminal Ctrl-C reaches the whole foreground process group, so
    lerobot-rollout usually has it already. Sending another would be its
    second signal, on which it force-exits (utils/process.py L85-99) and
    may cut short the drive back to the start pose. So the signal is
    forwarded only if LeRobot has not logged that it got one
    (``Shutdown signal ... received``, L89) within ``SHUTDOWN_GRACE_S``.
    """
    seen = len(lines)
    print(
        f"\n{PROG}: Ctrl-C: waiting for lerobot-rollout to stop and return the "
        f"follower to its start pose (up to {STOP_WAIT_S:.0f} s). Watch the arm.",
        file=sys.stderr,
    )
    if _wait(proc, SHUTDOWN_GRACE_S):
        return
    if not any(SHUTDOWN_LOG in line for line in lines[seen:]):
        print(f"{PROG}: forwarded Ctrl-C to lerobot-rollout.", file=sys.stderr)
        proc.send_signal(signal.SIGINT)
    if _wait(proc, STOP_WAIT_S):
        return
    print(
        f"{PROG}: lerobot-rollout did not exit in {STOP_WAIT_S:.0f} s; "
        "terminating it. Check the arm.",
        file=sys.stderr,
    )
    proc.terminate()
    if not _wait(proc, 5.0):
        proc.kill()
        proc.wait()


def run_teed(argv: list[str]) -> RunResult:
    """Run ``argv``, copying its output to our stdout line by line, and keep it.

    stderr is merged into stdout: LeRobot logs to stderr (a
    ``logging.StreamHandler`` with no stream, utils/utils.py L85-88).
    ``PYTHONUNBUFFERED`` keeps the child's lines from waiting in a pipe
    buffer. stdin is left alone and the child stays in our process group,
    so the keyboard controls still work: LeRobot reads keys with pynput's
    global listener or, on macOS without Accessibility permission, from
    stdin when it is a TTY (utils/keyboard_input.py L24-27, L269-275).

    A thread does the teeing, so output keeps flowing after a Ctrl-C while
    ``_stop_after_ctrl_c`` waits for LeRobot's clean shutdown.
    """
    env = os.environ | {"PYTHONUNBUFFERED": "1"}
    lines: list[str] = []
    interrupted = False
    proc: subprocess.Popen[str] | None = None
    reader: threading.Thread | None = None

    def tee(stream: IO[str]) -> None:
        for line in stream:
            sys.stdout.write(line)
            sys.stdout.flush()
            lines.append(line.rstrip("\r\n"))

    try:
        proc = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
        )
        assert proc.stdout is not None  # stdout=PIPE
        reader = threading.Thread(target=tee, args=(proc.stdout,), daemon=True)
        reader.start()
        proc.wait()
    except KeyboardInterrupt:
        if proc is None:
            raise
        interrupted = True
        _stop_after_ctrl_c(proc, lines)
    if reader is not None:
        reader.join(timeout=5.0)
    if proc.stdout is not None:
        proc.stdout.close()
    return RunResult(proc.returncode, lines, interrupted)


def _text(text: str) -> str:
    if not text.strip():
        raise argparse.ArgumentTypeError("must not be empty")
    return text


def _repo_id(text: str) -> str:
    if not _REPO_ID.fullmatch(text):
        raise argparse.ArgumentTypeError(f"expected USER/NAME, got {text!r}")
    if not text.split("/", 1)[1].startswith(ROLLOUT_PREFIX):
        raise argparse.ArgumentTypeError(
            f"LeRobot's rollout needs a name starting with {ROLLOUT_PREFIX!r}, "
            f"got {text!r}"
        )
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
    if not value > 0:
        raise argparse.ArgumentTypeError(f"must be more than 0, got {value}")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description=(
            "Run a trained LeRobot policy on the follower with lerobot-rollout, "
            "one episode per trial, and score each trial at a prompt. Never "
            "pushes to the Hugging Face Hub."
        ),
    )
    parser.add_argument(
        "--policy",
        required=True,
        type=Path,
        help="checkpoint folder, .../checkpoints/<step>/pretrained_model",
    )
    parser.add_argument("--task", required=True, type=_text, help="the task text")
    parser.add_argument(
        "--episodes", required=True, type=_positive_int, help="trials to run"
    )
    parser.add_argument(
        "--repo-id",
        type=_repo_id,
        help=f"eval dataset name (default: {REPO_OWNER}/rollout_<run>_<checkpoint>)",
    )
    parser.add_argument(
        "--dataset-root",
        type=Path,
        help="where to write the eval dataset, outside the workspace "
        "(default: $HF_LEROBOT_HOME/<repo id>)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="add the trials to the existing eval dataset at the dataset root",
    )
    parser.add_argument(
        "--train-dataset",
        type=Path,
        help="the dataset the policy was trained on "
        "(default: from the checkpoint's train_config.json)",
    )
    parser.add_argument(
        "--episode-time-s",
        type=_positive_float,
        default=PROTOCOL_EPISODE_TIME_S,
        help="time limit per trial, in seconds "
        f"(default: {PROTOCOL_EPISODE_TIME_S:.0f}, the #76 protocol's)",
    )
    parser.add_argument(
        "--reset-time-s",
        type=_positive_float,
        help="reset time after a re-recorded episode (left arrow)",
    )
    parser.add_argument(
        "--device", choices=("auto", "cuda", "mps", "cpu"), default="auto"
    )
    parser.add_argument(
        "--display", action="store_true", help="show the data live (--display_data)"
    )
    add_max_step_argument(parser)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="run the checks, print the plan and the command; runs nothing",
    )
    parser.add_argument(
        "--config", type=Path, help="machine config (default: configs/local.yaml)"
    )
    return parser


def _counts(dataset_root: Path) -> tuple[int, int | None]:
    """``(total_episodes, total_frames)`` from ``meta/info.json``.

    ``(0, 0)`` when there is no dataset yet; frames None if unreadable.
    """
    path = dataset_root / INFO_FILE
    if not path.is_file():
        return 0, 0
    try:
        info = json.loads(path.read_text())
        return int(info["total_episodes"]), int(info["total_frames"])
    except (OSError, ValueError, KeyError, TypeError):
        return 0, None


def _describe_rate(rate: ControlRate) -> str:
    late = f"{rate.slow_steps} late steps"
    if rate.slowest_step_hz is not None:
        late += f", slowest {rate.slowest_step_hz:.1f} Hz"
    if rate.hz is None:
        return f"Control rate: unknown (no frame count; {late})"
    return (
        f"Control rate: {rate.hz:.1f} Hz over {rate.frames} frames "
        f"(target {rate.target_fps} fps; {late})"
    )


def _refuse(problem: str) -> int:
    print(f"{PROG}: refusing to run: {problem}", file=sys.stderr)
    return 1


def _print_plan(
    policy: Policy,
    checkpoint: str,
    *,
    device: str,
    repo_id: str,
    dataset_root: Path,
    resume: bool,
    args: argparse.Namespace,
    log: Path,
    command: list[str],
) -> None:
    cameras = ", ".join(
        f"{name} {w}x{h}" for name, (h, w) in sorted(policy.cameras.items())
    )
    print("Calibration checked: follower passes (the leader is not used).")
    print(
        f"Policy: {policy.path} ({policy.policy_type}, checkpoint {checkpoint or '-'})"
    )
    print(f"Trained on: {policy.dataset_repo_id} at {policy.dataset_root}")
    print(f"Cameras checked: {cameras or 'none'} at {policy.dataset_fps} fps match")
    print(f"Device: {device}")
    print(
        "Teleop: none; after each trial LeRobot returns the follower to its start pose"
    )
    print(f"Dataset: {repo_id} ({'resume' if resume else 'new dataset'})")
    print(f"Dataset root: {dataset_root}")
    print(f"Task: {args.task}")
    print(f"Time limit: {args.episode_time_s} s per trial")
    print(
        f"Trials: {args.episodes} (one lerobot-rollout each; "
        "trials after the first add --resume=true)"
    )
    print("Push to Hub: no")
    print(describe_max_step(args.max_step, PROG))
    print(f"Trial log: {log}")
    print(f"Command: {format_command(command)}")


def main(
    argv: Sequence[str] | None = None,
    *,
    runner: Runner = run_teed,
    root: Path | None = None,
    lerobot_home: Path | None = None,
    ask: Ask = input,
    available_devices: Callable[[], set[str]] = available_devices,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> int:
    args = _parser().parse_args(argv)
    policy_path = args.policy.expanduser().absolute()
    run, checkpoint = run_name(policy_path)
    # One eval dataset per checkpoint, as for the trial log (trials_path).
    name = f"{run}_{checkpoint}" if checkpoint else run
    repo_id = args.repo_id or f"{REPO_OWNER}/{ROLLOUT_PREFIX}{name}"
    try:
        workspace = root if root is not None else find_workspace_root()
        config = load_local_config(workspace, args.config)
        problems = calibration_problems(config, workspace, roles=(ArmRole.FOLLOWER,))
        home = lerobot_home if lerobot_home is not None else default_lerobot_home()
        # Every problem found is named at once, so one rerun can fix them all.
        try:
            policy = load_policy(
                policy_path, train_dataset=args.train_dataset, lerobot_home=home
            )
        except PolicyError as err:
            problems.append(str(err))
            policy = None
        if policy is not None:
            problems += camera_problems(config, policy)
        if problems or policy is None:
            for problem in problems:
                _refuse(problem)
            return 1
        device = select_device(args.device, available_devices())
        if args.dataset_root is not None:
            dataset_root = args.dataset_root.expanduser().resolve()
        else:
            dataset_root = (home / repo_id).resolve()
        problem = dataset_root_problem(dataset_root, workspace, args.resume)
        if problem:
            return _refuse(problem)
        if args.resume:
            problems = eval_dataset_problems(dataset_root, policy)
            if problems:
                for problem in problems:
                    _refuse(problem)
                return 1

        def command(resume: bool) -> list[str]:
            return rollout_argv(
                config,
                workspace,
                policy_path=policy_path,
                repo_id=repo_id,
                dataset_root=dataset_root,
                task=args.task,
                fps=policy.dataset_fps,
                device=device,
                max_relative_target=args.max_step,
                episode_time_s=args.episode_time_s,
                reset_time_s=args.reset_time_s,
                resume=resume,
                display_data=args.display,
            )

        first = command(args.resume)
    except (WorkspaceError, PolicyError, ValueError) as err:
        print(f"{PROG}: {err}", file=sys.stderr)
        return 1

    if device == "mps":
        print(f"{PROG}: {MPS_WARNING}", file=sys.stderr)
    elif device == "cpu":
        print(f"{PROG}: {CPU_WARNING}", file=sys.stderr)
    log = trials_path(workspace, run, checkpoint)
    _print_plan(
        policy,
        checkpoint,
        device=device,
        repo_id=repo_id,
        dataset_root=dataset_root,
        resume=args.resume,
        args=args,
        log=log,
        command=first,
    )
    if args.dry_run:
        print("Start pose: not checked; each trial asks for y first.")
        print("Dry run: nothing was run.")
        return 0

    print(f"{PROG}: {START_POSE_WARNING}", file=sys.stderr)
    context: dict[str, Any] = {
        "policy": str(policy_path),
        "policy_resolved": str(policy_path.resolve()),
        "run": run,
        "checkpoint": checkpoint,
        "task": args.task,
        "device": device,
        "fps": policy.dataset_fps,
        "episode_time_s": args.episode_time_s,
        "max_relative_target": args.max_step,
        "dataset_repo_id": repo_id,
        "dataset_root": str(dataset_root),
    }
    scored: list[bool] = []
    rates: list[float | None] = []
    try:
        for i in range(args.episodes):
            resume = args.resume or i > 0
            if resume:
                problem = dataset_root_problem(dataset_root, workspace, resume=True)
                if problem:
                    return _refuse(problem)
            trial = count_trials(log) + 1
            try:
                answer = ask(
                    f"Trial {trial} ({i + 1} of {args.episodes}): is the follower at "
                    "its rest pose, the cube placed and the table clear? "
                    "Type y to start: "
                )
            except EOFError:
                answer = ""
            if answer.strip().lower() != "y":
                print("Stopped before the trial; nothing was run.")
                break
            episodes_before, frames_before = _counts(dataset_root)
            result = runner(command(resume))
            rollout_log = log.parent / LOGS_DIR / f"trial-{trial:03d}.log"
            rollout_log.parent.mkdir(parents=True, exist_ok=True)
            rollout_log.write_text("".join(f"{line}\n" for line in result.lines))
            if result.interrupted:
                print(
                    f"{PROG}: trial {trial} stopped (Ctrl-C) and is not scored; "
                    f"lerobot-rollout exited with {result.code}. Output: {rollout_log}",
                    file=sys.stderr,
                )
                return INTERRUPTED
            if result.code != 0:
                print(
                    f"{PROG}: lerobot-rollout exited with {result.code}; trial "
                    f"{trial} is not scored. Stopping. Output: {rollout_log}",
                    file=sys.stderr,
                )
                return result.code
            after, frames_after = _counts(dataset_root)
            saved = after > episodes_before
            frames = None
            if saved and frames_before is not None and frames_after is not None:
                frames = frames_after - frames_before
            rate = measure(result.lines, frames=frames, fps=policy.dataset_fps)
            print(_describe_rate(rate))
            if rate.low:
                print(
                    f"{PROG}: WARNING: trial {trial} ran at {rate.hz:.1f} Hz, below "
                    f"{LOW_HZ:.0f} Hz. Note it with the result (#76); #82 asks for "
                    "one diagnostic rerun with --device cpu or without --display. "
                    f"{CAP_COST_NOTE}",
                    file=sys.stderr,
                )
            try:
                score = ask_score(ask)
            except EOFError:
                print(
                    f"\n{PROG}: input ended; trial {trial} is not scored.",
                    file=sys.stderr,
                )
                return 1
            record = trial_record(
                score,
                trial=trial,
                episode_index=after - 1 if saved else None,
                now=now(),
                context=context
                | {
                    "control_hz": rate.hz,
                    "frames": rate.frames,
                    "slow_steps": rate.slow_steps,
                    "slowest_step_hz": rate.slowest_step_hz,
                    "rollout_log": str(rollout_log),
                },
            )
            append_trial(log, record)
            scored.append(score.success)
            rates.append(rate.hz)
            print(f"Trial {trial} logged to {log}")
    except KeyboardInterrupt:
        print(
            f"\n{PROG}: stopped (Ctrl-C) at a prompt; the trials scored so far "
            f"are in {log}.",
            file=sys.stderr,
        )
        return INTERRUPTED
    measured = ", ".join("?" if hz is None else f"{hz:.1f}" for hz in rates)
    print(
        f"This session: {sum(scored)}/{len(scored)} succeeded; control rate per "
        f"trial (Hz): {measured or '-'}. Log: {log}"
    )
    return 0


def cli() -> None:
    sys.exit(main())
