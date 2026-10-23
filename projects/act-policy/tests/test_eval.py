"""``so101-eval`` end to end, with a fake runner and fake answers.

The fake runner stands in for ``evaluate.run_teed(argv)`` on
``lerobot-rollout``: it returns the exit code and the output lines, and
leaves on disk what one episodic rollout of one episode leaves: the dataset
metadata LeRobot reads back on ``--resume`` (the files
``hw_setup.record.missing_metadata`` checks), with ``total_episodes`` and
``total_frames`` counting up. Its output lines are LeRobot's own format
(the ``slow_line`` fixture). No robot, camera or policy is run.
"""

import json
import shutil
import sys
import time
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path

import pytest

from act_policy import evaluate
from act_policy.evaluate import RunResult, main, run_teed

MakePolicy = Callable[..., Path]
TASK = "Pick the cube and place it in the bin"
ALL = frozenset({"cuda", "mps", "cpu"})


class Answers:
    def __init__(self, *answers: str) -> None:
        self._answers: Iterator[str] = iter(answers)
        self.prompts: list[str] = []

    def __call__(self, prompt: str = "") -> str:
        self.prompts.append(prompt)
        try:
            return next(self._answers)
        except StopIteration:
            raise EOFError from None


def no_input(prompt: str = "") -> str:
    raise AssertionError(f"unexpected prompt: {prompt}")


class FakeRollout:
    """Records each argv; writes the dataset metadata one episode leaves."""

    def __init__(
        self,
        code: int = 0,
        saves: bool = True,
        frames: int = 900,
        output: Sequence[Sequence[str]] = (),
        interrupted: bool = False,
        cameras: dict[str, tuple[int, int]] | None = None,
    ) -> None:
        self.interrupted = interrupted
        self.cameras = cameras or {"front": (480, 640), "wrist": (480, 640)}
        self.calls: list[list[str]] = []
        self.code = code
        self.saves = saves
        self.frames = frames
        self.output = list(output)  # one list of lines per call

    def __call__(self, argv: list[str]) -> RunResult:
        self.calls.append(argv)
        root = Path(flag(argv, "--dataset.root"))
        info_path = root / "meta" / "info.json"
        info = json.loads(info_path.read_text()) if info_path.is_file() else {}
        # What LeRobotDataset.create writes (rollout/context.py L436-441):
        # the control fps and the robot's camera features, (h, w, c).
        info.setdefault("fps", int(flag(argv, "--dataset.fps")))
        info.setdefault(
            "features",
            {
                f"observation.images.{name}": {
                    "dtype": "video",
                    "shape": [h, w, 3],
                    "names": ["height", "width", "channels"],
                }
                for name, (h, w) in self.cameras.items()
            },
        )
        if self.saves:
            info["total_episodes"] = info.get("total_episodes", 0) + 1
            info["total_frames"] = info.get("total_frames", 0) + self.frames
            info["total_tasks"] = 1
            episodes = root / "meta" / "episodes" / "chunk-000"
            episodes.mkdir(parents=True, exist_ok=True)
            (episodes / "file-000.parquet").write_bytes(b"PAR1")
            (root / "meta" / "tasks.parquet").write_bytes(b"PAR1")
        info_path.parent.mkdir(parents=True, exist_ok=True)
        info_path.write_text(json.dumps(info))
        index = len(self.calls) - 1
        lines = list(self.output[index]) if index < len(self.output) else []
        return RunResult(self.code, lines, interrupted=self.interrupted)


def flag(argv: list[str], name: str) -> str:
    (value,) = [a.split("=", 1)[1] for a in argv if a.startswith(f"{name}=")]
    return value


def run(
    workspace: Path,
    lerobot_home: Path,
    args: list[str],
    *,
    runner: FakeRollout | None = None,
    ask: Callable[[str], str] = no_input,
    devices: frozenset[str] = ALL,
) -> int:
    return main(
        args,
        runner=runner or FakeRollout(),
        root=workspace,
        lerobot_home=lerobot_home,
        ask=ask,
        available_devices=lambda: set(devices),
    )


def base_args(policy: Path, episodes: int = 1) -> list[str]:
    return ["--policy", str(policy), "--task", TASK, "--episodes", str(episodes)]


def trials_file(workspace: Path) -> Path:
    return workspace / "outputs" / "eval" / "act_pick_cube" / "last" / "trials.jsonl"


def read_trials(workspace: Path) -> list[dict]:
    path = trials_file(workspace)
    return [json.loads(line) for line in path.read_text().splitlines()]


# --- dry run -------------------------------------------------------------


def test_dry_run_prints_the_plan_and_runs_nothing(
    workspace: Path,
    lerobot_home: Path,
    make_policy: MakePolicy,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runner = FakeRollout()
    args = [*base_args(make_policy(), 10), "--dry-run"]
    assert run(workspace, lerobot_home, args, runner=runner) == 0
    out = capsys.readouterr().out
    assert runner.calls == []
    assert "Command: lerobot-rollout --strategy.type=episodic" in out
    assert "--dataset.push_to_hub=false" in out
    assert "Push to Hub: no" in out
    assert "Teleop: none" in out
    assert "Trials: 10" in out
    assert "Device: cuda" in out
    assert f"{lerobot_home / 'local' / 'rollout_act_pick_cube_last'}" in out
    assert "Dry run: nothing was run." in out
    assert not (workspace / "outputs").exists()
    assert not lerobot_home.exists()


def test_dry_run_command_has_no_teleop(
    workspace: Path,
    lerobot_home: Path,
    make_policy: MakePolicy,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run(workspace, lerobot_home, [*base_args(make_policy()), "--dry-run"])
    command = capsys.readouterr().out.split("Command: ", 1)[1].splitlines()[0]
    assert "--teleop" not in command
    assert "--robot.max_relative_target=5.0" in command


def test_max_step_reaches_the_command(
    workspace: Path,
    lerobot_home: Path,
    make_policy: MakePolicy,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = [*base_args(make_policy()), "--max-step", "2", "--dry-run"]
    run(workspace, lerobot_home, args)
    assert "--robot.max_relative_target=2.0" in capsys.readouterr().out


# --- gates ---------------------------------------------------------------


def test_follower_calibration_gate_refuses_even_in_dry_run(
    workspace: Path,
    lerobot_home: Path,
    make_policy: MakePolicy,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (workspace / "hardware" / "calibration" / "follower" / "main.json").unlink()
    args = [*base_args(make_policy()), "--dry-run"]
    assert run(workspace, lerobot_home, args) == 1
    assert "follower arm (main): calibration missing" in capsys.readouterr().err


def test_leader_calibration_is_not_needed(
    workspace: Path, lerobot_home: Path, make_policy: MakePolicy
) -> None:
    (workspace / "hardware" / "calibration" / "leader" / "main.json").unlink()
    args = [*base_args(make_policy()), "--dry-run"]
    assert run(workspace, lerobot_home, args) == 0


def test_missing_policy_is_refused(
    workspace: Path,
    lerobot_home: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = [*base_args(tmp_path / "nope"), "--dry-run"]
    assert run(workspace, lerobot_home, args) == 1
    assert "not a folder" in capsys.readouterr().err


def test_camera_mismatch_is_refused(
    workspace: Path,
    lerobot_home: Path,
    make_policy: MakePolicy,
    capsys: pytest.CaptureFixture[str],
) -> None:
    one = {"front": (480, 640)}
    policy = make_policy(cameras=one, dataset_cameras=one)
    assert run(workspace, lerobot_home, [*base_args(policy), "--dry-run"]) == 1
    err = capsys.readouterr().err
    assert "refusing to run" in err and "wrist" in err


def test_unavailable_device_is_refused(
    workspace: Path,
    lerobot_home: Path,
    make_policy: MakePolicy,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = [*base_args(make_policy()), "--device", "cuda", "--dry-run"]
    assert run(workspace, lerobot_home, args, devices=frozenset({"cpu"})) == 1
    assert "cuda is not available" in capsys.readouterr().err


def test_mps_prints_the_control_rate_risk(
    workspace: Path,
    lerobot_home: Path,
    make_policy: MakePolicy,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = [*base_args(make_policy()), "--dry-run"]
    run(workspace, lerobot_home, args, devices=frozenset({"mps", "cpu"}))
    captured = capsys.readouterr()
    assert "Device: mps" in captured.out
    assert "15 Hz" in captured.err and "25 Hz" in captured.err
    assert "movement cap" in captured.err


def test_dataset_root_inside_the_workspace_is_refused(
    workspace: Path,
    lerobot_home: Path,
    make_policy: MakePolicy,
    capsys: pytest.CaptureFixture[str],
) -> None:
    inside = workspace / "outputs" / "rollout"
    args = [*base_args(make_policy()), "--dataset-root", str(inside), "--dry-run"]
    assert run(workspace, lerobot_home, args) == 1
    assert "inside the workspace" in capsys.readouterr().err


def test_existing_dataset_root_needs_resume(
    workspace: Path,
    lerobot_home: Path,
    make_policy: MakePolicy,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = lerobot_home / "local" / "rollout_act_pick_cube_last"
    FakeRollout()(["x", f"--dataset.root={root}", "--dataset.fps=30"])
    args = [*base_args(make_policy()), "--dry-run"]
    assert run(workspace, lerobot_home, args) == 1
    assert "--resume" in capsys.readouterr().err
    assert run(workspace, lerobot_home, [*args, "--resume"]) == 0


def test_repo_id_must_start_with_rollout(
    workspace: Path, lerobot_home: Path, make_policy: MakePolicy
) -> None:
    args = [*base_args(make_policy()), "--repo-id", "local/eval_x", "--dry-run"]
    with pytest.raises(SystemExit) as exit_info:
        run(workspace, lerobot_home, args)
    assert exit_info.value.code == 2


# --- trials --------------------------------------------------------------


def test_each_trial_runs_one_episode_and_is_scored(
    workspace: Path,
    lerobot_home: Path,
    make_policy: MakePolicy,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runner = FakeRollout()
    ask = Answers(
        "y",  # start trial 1
        "n",  # success?
        "grasp",
        "3",
        "dropped it",
        "y",  # start trial 2
        "y",  # success?
        "1",
        "",
    )
    policy = make_policy()
    args = [*base_args(policy, 2), "--episode-time-s", "30"]
    assert run(workspace, lerobot_home, args, runner=runner, ask=ask) == 0

    assert len(runner.calls) == 2
    first, second = runner.calls
    assert "--resume=true" not in first
    assert "--resume=true" in second
    assert all("--dataset.num_episodes=1" in call for call in runner.calls)
    assert flag(first, "--dataset.root") == str(
        lerobot_home / "local" / "rollout_act_pick_cube_last"
    )

    trials = read_trials(workspace)
    assert [t["trial"] for t in trials] == [1, 2]
    assert [t["episode_index"] for t in trials] == [0, 1]
    assert [t["success"] for t in trials] == [False, True]
    assert [t["stage"] for t in trials] == ["grasp", "released in the bin"]
    assert [t["start_position"] for t in trials] == ["3", "1"]
    assert trials[0]["notes"] == "dropped it"
    assert trials[0]["policy"] == str(policy)
    assert trials[0]["checkpoint"] == "last"
    assert trials[0]["task"] == TASK
    assert trials[0]["device"] == "cuda"
    assert trials[0]["fps"] == 30
    assert trials[0]["episode_time_s"] == 30.0
    assert trials[0]["max_relative_target"] == 5.0
    assert trials[0]["dataset_repo_id"] == "local/rollout_act_pick_cube_last"
    assert trials[0]["time_utc"].endswith("Z")
    assert "1/2 succeeded" in capsys.readouterr().out


def test_start_prompt_warns_that_the_start_pose_is_not_checked(
    workspace: Path,
    lerobot_home: Path,
    make_policy: MakePolicy,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ask = Answers("n")
    runner = FakeRollout()
    assert (
        run(workspace, lerobot_home, base_args(make_policy()), runner=runner, ask=ask)
        == 0
    )
    assert runner.calls == []
    assert "rest pose" in ask.prompts[0]
    err = capsys.readouterr().err
    assert "start pose is not checked" in err
    assert "loses torque" in err and "support the arm" in err
    assert not (workspace / "outputs").exists()


def test_a_failed_rollout_stops_without_a_trial_row(
    workspace: Path, lerobot_home: Path, make_policy: MakePolicy
) -> None:
    runner = FakeRollout(code=3)
    ask = Answers("y")
    args = base_args(make_policy(), 2)
    assert run(workspace, lerobot_home, args, runner=runner, ask=ask) == 3
    assert len(runner.calls) == 1
    assert not (trials_file(workspace)).exists()


def test_an_episode_that_was_not_saved_has_no_index(
    workspace: Path, lerobot_home: Path, make_policy: MakePolicy
) -> None:
    ask = Answers("y", "n", "none", "", "escaped at once")
    runner = FakeRollout(saves=False)
    assert (
        run(workspace, lerobot_home, base_args(make_policy()), runner=runner, ask=ask)
        == 0
    )
    (trial,) = read_trials(workspace)
    assert trial["episode_index"] is None


def test_trial_numbers_continue_across_sessions(
    workspace: Path, lerobot_home: Path, make_policy: MakePolicy
) -> None:
    policy = make_policy()
    first = Answers("y", "y", "1", "")
    assert run(workspace, lerobot_home, base_args(policy), ask=first) == 0
    second = Answers("y", "n", "reach", "2", "")
    args = [*base_args(policy), "--resume"]
    assert run(workspace, lerobot_home, args, ask=second) == 0
    trials = read_trials(workspace)
    assert [t["trial"] for t in trials] == [1, 2]
    assert [t["episode_index"] for t in trials] == [0, 1]


def test_ctrl_d_at_a_prompt_stops_cleanly(
    workspace: Path, lerobot_home: Path, make_policy: MakePolicy
) -> None:
    ask = Answers("y", "n")  # input ends while scoring
    runner = FakeRollout()
    args = base_args(make_policy(), 3)
    assert run(workspace, lerobot_home, args, runner=runner, ask=ask) == 1
    assert len(runner.calls) == 1
    assert not (trials_file(workspace)).exists()


# --- control rate --------------------------------------------------------


def test_the_control_rate_is_logged_per_trial(
    workspace: Path,
    lerobot_home: Path,
    make_policy: MakePolicy,
    slow_line: Callable[..., str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Trial 1: every one of 300 steps late at 15 Hz. Trial 2: none late.
    runner = FakeRollout(frames=300, output=[[slow_line(15.0)] * 300, ["INFO ok"]])
    ask = Answers("y", "n", "2", "", "", "y", "y", "", "")
    args = base_args(make_policy(), 2)
    assert run(workspace, lerobot_home, args, runner=runner, ask=ask) == 0
    first, second = read_trials(workspace)
    assert first["control_hz"] == pytest.approx(15.0)
    assert first["slow_steps"] == 300
    assert first["slowest_step_hz"] == 15.0
    assert first["frames"] == 300
    assert second["control_hz"] == pytest.approx(30.0)
    assert second["slow_steps"] == 0
    assert second["slowest_step_hz"] is None
    captured = capsys.readouterr()
    assert captured.err.count("below 25 Hz") == 1
    assert "trial 1 ran at 15.0 Hz" in captured.err
    # The cap reads the follower's position on every step (so_follower.py
    # L221-226, "Slower fps expected"), so the advice names it.
    assert "movement cap" in captured.err and "bus read" in captured.err
    assert "Control rate: 15.0 Hz" in captured.out
    assert "Control rate: 30.0 Hz" in captured.out


def test_the_rollout_output_is_kept_per_trial(
    workspace: Path,
    lerobot_home: Path,
    make_policy: MakePolicy,
    slow_line: Callable[..., str],
) -> None:
    runner = FakeRollout(output=[["INFO a", slow_line(20.0)]])
    ask = Answers("y", "y", "", "")
    assert (
        run(workspace, lerobot_home, base_args(make_policy()), runner=runner, ask=ask)
        == 0
    )
    log = trials_file(workspace).parent / "logs" / "trial-001.log"
    assert log.read_text().splitlines() == ["INFO a", slow_line(20.0)]
    (trial,) = read_trials(workspace)
    assert trial["rollout_log"] == str(log)


def test_run_teed_shows_and_returns_the_output(
    capfd: pytest.CaptureFixture[str],
) -> None:
    code = "import sys; print('to out'); print('to err', file=sys.stderr); sys.exit(3)"
    result = run_teed([sys.executable, "-c", code])
    assert result.code == 3
    assert sorted(result.lines) == ["to err", "to out"]
    out = capfd.readouterr().out
    assert "to out" in out and "to err" in out


# --- Ctrl-C during a trial -------------------------------------------------

# A child that handles SIGINT as LeRobot 0.6.1 does (utils/process.py
# L85-99): the first signal logs "Shutdown signal 2 received. Cleaning up…"
# and starts a clean shutdown; a second one force-exits with status 1. The
# clean shutdown takes about 1 s, standing in for the follower's drive back
# to its start pose. ``TARGETS`` says who the child signals once it is
# running: the parent only, or the parent and itself, as a terminal Ctrl-C
# reaches the whole foreground process group.
GRACEFUL_CHILD = """
import logging, os, signal, sys, time
logging.basicConfig(level=logging.INFO, format="INFO %(message)s")
count = 0
def handler(signum, frame):
    global count
    count += 1
    logging.info(f" Shutdown signal {signum} received. Cleaning up…")
    if count > 1:
        logging.info("Force shutdown")
        sys.exit(1)
signal.signal(signal.SIGINT, handler)
signal.signal(signal.SIGTERM, handler)
print("rollout running", flush=True)
time.sleep(0.3)
for pid in TARGETS:
    os.kill(pid, signal.SIGINT)
    time.sleep(GAP)
while count == 0:
    time.sleep(0.01)
AFTER
print("done", flush=True)
"""
# LeRobot's own lines, copied: rollout/strategies/core.py L127 and L134.
RETURN_LINE = "INFO Returning robot to initial position before shutdown..."
DISCONNECT_LINE = "INFO Disconnecting robot..."
RETURN_1S = """
print("returning to start pose", flush=True)
time.sleep(1.0)
"""


def graceful_child(targets: str, gap: float = 0.0, after: str = RETURN_1S) -> list[str]:
    code = (
        GRACEFUL_CHILD.replace("TARGETS", targets)
        .replace("GAP", str(gap))
        .replace("AFTER", after)
    )
    return [sys.executable, "-c", code]


def test_ctrl_c_is_not_forwarded_when_lerobot_logged_it_first(
    capfd: pytest.CaptureFixture[str],
) -> None:
    # The child gets the signal and logs it before the parent is
    # interrupted, so the log line is already teed when so101-eval looks.
    result = run_teed(graceful_child("(os.getpid(), os.getppid())", gap=0.3))
    assert result.interrupted is True
    assert result.code == 0  # a forwarded second SIGINT would force status 1
    assert "forwarded" not in capfd.readouterr().err


def test_ctrl_c_waits_for_lerobot_to_finish_and_does_not_signal_twice(
    capfd: pytest.CaptureFixture[str],
) -> None:
    started = time.monotonic()
    result = run_teed(graceful_child("(os.getppid(), os.getpid())"))
    assert time.monotonic() - started >= 1.0
    assert result.interrupted is True
    assert result.code == 0  # a second SIGINT would have forced status 1
    assert "done" in result.lines
    assert not any("Force shutdown" in line for line in result.lines)
    captured = capfd.readouterr()
    assert "done" in captured.out  # still teed after the Ctrl-C
    assert "waiting for lerobot-rollout" in captured.err


def test_ctrl_c_is_forwarded_when_the_child_did_not_get_it(
    capfd: pytest.CaptureFixture[str],
) -> None:
    result = run_teed(graceful_child("(os.getppid(),)"))
    assert result.interrupted is True
    assert result.code == 0
    assert any("Shutdown signal 2 received" in line for line in result.lines)
    assert "done" in result.lines
    assert "forwarded Ctrl-C" in capfd.readouterr().err


def test_an_interrupted_trial_is_not_scored(
    workspace: Path, lerobot_home: Path, make_policy: MakePolicy
) -> None:
    runner = FakeRollout(interrupted=True)
    ask = Answers("y")
    args = base_args(make_policy(), 3)
    assert run(workspace, lerobot_home, args, runner=runner, ask=ask) == 130
    assert len(runner.calls) == 1
    assert len(ask.prompts) == 1
    assert not trials_file(workspace).exists()


def test_ctrl_c_at_a_prompt_exits_without_a_traceback(
    workspace: Path,
    lerobot_home: Path,
    make_policy: MakePolicy,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def interrupt(prompt: str = "") -> str:
        raise KeyboardInterrupt

    assert run(workspace, lerobot_home, base_args(make_policy()), ask=interrupt) == 130
    assert "stopped (Ctrl-C)" in capsys.readouterr().err


def test_cli_is_wired() -> None:
    assert callable(evaluate.cli)


def test_the_time_limit_defaults_to_the_76_protocol(
    workspace: Path,
    lerobot_home: Path,
    make_policy: MakePolicy,
    capsys: pytest.CaptureFixture[str],
) -> None:
    policy = make_policy()
    run(workspace, lerobot_home, [*base_args(policy), "--dry-run"])
    out = capsys.readouterr().out
    assert "--dataset.episode_time_s=30.0" in out
    assert "Time limit: 30.0 s per trial" in out
    ask = Answers("y", "y", "", "")
    assert run(workspace, lerobot_home, base_args(policy), ask=ask) == 0
    (trial,) = read_trials(workspace)
    assert trial["episode_time_s"] == 30.0


def test_two_checkpoints_of_one_run_never_share_a_dataset_or_a_log(
    workspace: Path,
    lerobot_home: Path,
    make_policy: MakePolicy,
    capsys: pytest.CaptureFixture[str],
) -> None:
    last = make_policy()
    step = last.parents[1] / "050000" / "pretrained_model"
    shutil.copytree(last, step)
    for policy in (last, step):
        ask = Answers("y", "y", "", "")
        assert run(workspace, lerobot_home, base_args(policy), ask=ask) == 0
    evals = workspace / "outputs" / "eval" / "act_pick_cube"
    for checkpoint in ("last", "050000"):
        (trial,) = [
            json.loads(x)
            for x in (evals / checkpoint / "trials.jsonl").read_text().splitlines()
        ]
        assert trial["trial"] == 1
        assert trial["checkpoint"] == checkpoint
        assert trial["dataset_repo_id"] == f"local/rollout_act_pick_cube_{checkpoint}"
        assert (lerobot_home / "local" / f"rollout_act_pick_cube_{checkpoint}").is_dir()


def eval_dataset(
    lerobot_home: Path, cameras: dict[str, tuple[int, int]] | None = None
) -> Path:
    """An eval dataset left by an earlier session, at the default root."""
    root = lerobot_home / "local" / "rollout_act_pick_cube_last"
    FakeRollout(cameras=cameras)(["x", f"--dataset.root={root}", "--dataset.fps=30"])
    return root


def test_resume_refuses_an_eval_dataset_at_another_fps(
    workspace: Path,
    lerobot_home: Path,
    make_policy: MakePolicy,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = eval_dataset(lerobot_home)
    info = json.loads((root / "meta" / "info.json").read_text())
    (root / "meta" / "info.json").write_text(json.dumps(info | {"fps": 15}))
    args = [*base_args(make_policy()), "--resume", "--dry-run"]
    assert run(workspace, lerobot_home, args) == 1
    err = capsys.readouterr().err
    assert "eval dataset" in err and "15 fps" in err and "30 fps" in err


def test_resume_refuses_an_eval_dataset_with_other_cameras(
    workspace: Path,
    lerobot_home: Path,
    make_policy: MakePolicy,
    capsys: pytest.CaptureFixture[str],
) -> None:
    eval_dataset(lerobot_home, cameras={"front": (240, 320), "top": (480, 640)})
    args = [*base_args(make_policy()), "--resume", "--dry-run"]
    assert run(workspace, lerobot_home, args) == 1
    err = capsys.readouterr().err
    assert "top" in err and "320x240" in err


def test_calibration_and_policy_problems_are_reported_together(
    workspace: Path,
    lerobot_home: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (workspace / "hardware" / "calibration" / "follower" / "main.json").unlink()
    args = [*base_args(tmp_path / "nope"), "--dry-run"]
    assert run(workspace, lerobot_home, args) == 1
    err = capsys.readouterr().err
    assert "calibration missing" in err and "not a folder" in err
