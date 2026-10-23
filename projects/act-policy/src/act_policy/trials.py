"""Score each eval episode at a prompt and append it to ``trials.jsonl``.

The fields follow the eval protocol pre-registered in #76 and run in #82:
pass or fail, the furthest stage reached, the start position and notes (the
failure mode). The stage names and the success definition are #76's, word
for word. A success always reaches the last stage, ``released in the bin``;
a fail can too (a touch or an Escape is a fail whatever the cube did).

The log is ``outputs/eval/<run>/<checkpoint>/trials.jsonl`` in the workspace
(``outputs/`` is gitignored): one JSON object per line, appended and flushed
as soon as an episode is scored, so a crash or Ctrl-C keeps every trial
scored before it.
"""

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# "Score each trial on stages (reach, grasp, lift, over the bin, released in
# the bin)" (#76), with "none" first for a trial that reached none of them.
STAGES = ("none", "reach", "grasp", "lift", "over the bin", "released in the bin")
SUCCESS_DEFINITION = (
    "the cube ends up inside the bin and released, within 30 s, with no human "
    "touch, and the arm stops without hitting the bin or table hard enough to "
    "move them"
)
EVAL_DIR = Path("outputs") / "eval"
TRIALS_FILE = "trials.jsonl"

Ask = Callable[[str], str]


@dataclass(frozen=True)
class Score:
    success: bool
    stage: str
    start_position: str
    notes: str


def _choose(ask: Ask, prompt: str, choices: Mapping[str, Any]) -> Any:
    while True:
        answer = ask(prompt).strip().lower()
        if answer in choices:
            return choices[answer]
        print(f"  Please answer one of: {', '.join(choices)}")


def ask_score(ask: Ask) -> Score:
    """Ask for the score; asks again on an answer it does not know.

    ``ask`` is ``input`` in use; EOFError (Ctrl-D) and KeyboardInterrupt
    propagate, and nothing is scored.
    """
    success = _choose(
        ask,
        f"Success ({SUCCESS_DEFINITION})? [y/n] ",
        {"y": True, "n": False},
    )
    if success:
        stage = STAGES[-1]
    else:
        menu = ", ".join(f"{i} {name}" for i, name in enumerate(STAGES))
        choices = {name: name for name in STAGES}
        choices |= {str(i): name for i, name in enumerate(STAGES)}
        stage = _choose(ask, f"Furthest stage reached ({menu}): ", choices)
    start_position = ask("Start position (blank if none): ").strip()
    notes = ask("Notes or failure mode (blank if none): ").strip()
    return Score(success, stage, start_position, notes)


def trial_record(
    score: Score,
    *,
    trial: int,
    episode_index: int | None,
    now: datetime,
    context: Mapping[str, Any],
) -> dict[str, Any]:
    """One line of trials.jsonl: the score, then the run's settings."""
    return {
        "trial": trial,
        "interrupted": False,
        "episode_index": episode_index,
        "time_utc": now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "success": score.success,
        "stage": score.stage,
        "start_position": score.start_position,
        "notes": score.notes,
        **context,
    }


def interrupted_record(
    *,
    trial: int,
    episode_index: int | None,
    now: datetime,
    context: Mapping[str, Any],
) -> dict[str, Any]:
    """A trial stopped with Ctrl-C: logged, never scored.

    LeRobot still saves its episode, so the row keeps the eval dataset's
    episode count and the log in step. ``success`` and ``stage`` are null;
    leave such rows out of the success rate.
    """
    return {
        "trial": trial,
        "interrupted": True,
        "episode_index": episode_index,
        "time_utc": now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "success": None,
        "stage": None,
        "start_position": "",
        "notes": "stopped with Ctrl-C; not scored",
        **context,
    }


def trials_path(workspace: Path, run: str, checkpoint: str) -> Path:
    """``outputs/eval/<run>/<checkpoint>/trials.jsonl``, one per checkpoint.

    #76 allows evaluating more than one checkpoint ("report all of them"),
    so two checkpoints of one run never share a log. Without a checkpoint
    name the run's folder is used.
    """
    folder = workspace / EVAL_DIR / run
    if checkpoint:
        folder = folder / checkpoint
    return folder / TRIALS_FILE


def count_trials(path: Path) -> int:
    """Trials already in the log (non-blank lines); 0 when there is none."""
    if not path.is_file():
        return 0
    return sum(1 for line in path.read_text().splitlines() if line.strip())


def append_trial(path: Path, record: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(record) + "\n")
        f.flush()
