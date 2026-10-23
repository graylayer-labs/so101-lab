"""Score each eval episode at a prompt and append it to ``trials.jsonl``.

The fields follow the eval protocol for #82 (pre-registered in #76): pass or
fail, the furthest stage reached, the start position and notes (the failure
mode). A success means the cube ended in the bin and was released, within
the time limit and with no human touch, so a success is always scored at
the last stage, ``release``.

The log is ``outputs/eval/<run>/trials.jsonl`` in the workspace (``outputs/``
is gitignored): one JSON object per line, appended and flushed as soon as an
episode is scored, so a crash or Ctrl-C keeps every trial scored before it.
"""

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

STAGES = ("none", "reach", "grasp", "place", "release")
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
        "Success: cube released in the bin, no touch, in time? [y/n] ",
        {"y": True, "n": False},
    )
    if success:
        stage = "release"
    else:
        stage = _choose(
            ask,
            f"Furthest stage reached [{'/'.join(STAGES)}]: ",
            {s: s for s in STAGES},
        )
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
        "episode_index": episode_index,
        "time_utc": now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "success": score.success,
        "stage": score.stage,
        "start_position": score.start_position,
        "notes": score.notes,
        **context,
    }


def trials_path(workspace: Path, run: str) -> Path:
    return workspace / EVAL_DIR / run / TRIALS_FILE


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
