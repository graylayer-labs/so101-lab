"""``so101-eval`` end to end, with a fake runner and fake answers.

The fake runner stands in for ``subprocess.run(argv)`` on ``lerobot-rollout``
and leaves on disk what one episodic rollout of one episode leaves: the
dataset metadata LeRobot reads back on ``--resume`` (the files
``hw_setup.record.missing_metadata`` checks), with ``total_episodes``
counting up. No robot, camera or policy is run.
"""

import json
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from act_policy import evaluate
from act_policy.evaluate import main

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

    def __init__(self, code: int = 0, saves: bool = True) -> None:
        self.calls: list[list[str]] = []
        self.code = code
        self.saves = saves

    def __call__(self, argv: list[str]) -> int:
        self.calls.append(argv)
        root = Path(flag(argv, "--dataset.root"))
        info_path = root / "meta" / "info.json"
        info = json.loads(info_path.read_text()) if info_path.is_file() else {}
        if self.saves:
            info["total_episodes"] = info.get("total_episodes", 0) + 1
            info["total_tasks"] = 1
            episodes = root / "meta" / "episodes" / "chunk-000"
            episodes.mkdir(parents=True, exist_ok=True)
            (episodes / "file-000.parquet").write_bytes(b"PAR1")
            (root / "meta" / "tasks.parquet").write_bytes(b"PAR1")
        info_path.parent.mkdir(parents=True, exist_ok=True)
        info_path.write_text(json.dumps(info))
        return self.code


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


def read_trials(workspace: Path) -> list[dict]:
    path = workspace / "outputs" / "eval" / "act_pick_cube" / "trials.jsonl"
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
    assert f"{lerobot_home / 'local' / 'rollout_act_pick_cube'}" in out
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
    root = lerobot_home / "local" / "rollout_act_pick_cube"
    FakeRollout()(["x", f"--dataset.root={root}"])
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
        lerobot_home / "local" / "rollout_act_pick_cube"
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
    assert trials[0]["dataset_repo_id"] == "local/rollout_act_pick_cube"
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
    assert "start pose is not checked" in capsys.readouterr().err
    assert not (workspace / "outputs").exists()


def test_a_failed_rollout_stops_without_a_trial_row(
    workspace: Path, lerobot_home: Path, make_policy: MakePolicy
) -> None:
    runner = FakeRollout(code=3)
    ask = Answers("y")
    args = base_args(make_policy(), 2)
    assert run(workspace, lerobot_home, args, runner=runner, ask=ask) == 3
    assert len(runner.calls) == 1
    assert not (workspace / "outputs" / "eval").exists()


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
    assert not (workspace / "outputs" / "eval").exists()


def test_cli_is_wired() -> None:
    assert callable(evaluate.cli)
