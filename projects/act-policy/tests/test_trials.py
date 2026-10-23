"""Scoring prompts and the trials.jsonl log."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from act_policy.trials import (
    STAGES,
    Score,
    append_trial,
    ask_score,
    count_trials,
    trial_record,
    trials_path,
)


class Answers:
    """Stands in for ``input``: returns the answers in order, records prompts."""

    def __init__(self, *answers: str) -> None:
        self._answers: Iterator[str] = iter(answers)
        self.prompts: list[str] = []

    def __call__(self, prompt: str = "") -> str:
        self.prompts.append(prompt)
        try:
            return next(self._answers)
        except StopIteration:
            raise EOFError from None


def test_stages_are_the_eval_protocol_ones() -> None:
    assert STAGES == ("none", "reach", "grasp", "place", "release")


def test_a_success_is_scored_as_released() -> None:
    ask = Answers("y", "2", "clean")
    assert ask_score(ask) == Score(
        success=True, stage="release", start_position="2", notes="clean"
    )
    assert len(ask.prompts) == 3


def test_a_fail_asks_for_the_furthest_stage() -> None:
    ask = Answers("n", "grasp", "", "dropped over the bin")
    assert ask_score(ask) == Score(
        success=False, stage="grasp", start_position="", notes="dropped over the bin"
    )


def test_bad_answers_are_asked_again() -> None:
    ask = Answers("maybe", "N", "lift", "PLACE", "4", "")
    score = ask_score(ask)
    assert score.success is False
    assert score.stage == "place"
    assert len(ask.prompts) == 6


def test_end_of_input_is_not_scored() -> None:
    with pytest.raises(EOFError):
        ask_score(Answers("n"))


def test_record_fields() -> None:
    now = datetime(2026, 11, 2, 14, 30, 5, tzinfo=UTC)
    record = trial_record(
        Score(success=False, stage="reach", start_position="1", notes=""),
        trial=3,
        episode_index=2,
        now=now,
        context={"policy": "/p", "device": "mps"},
    )
    assert record == {
        "trial": 3,
        "episode_index": 2,
        "time_utc": "2026-11-02T14:30:05Z",
        "success": False,
        "stage": "reach",
        "start_position": "1",
        "notes": "",
        "policy": "/p",
        "device": "mps",
    }


def test_records_append_one_json_line_each(tmp_path: Path) -> None:
    path = trials_path(tmp_path, "act_pick_cube")
    assert path == tmp_path / "outputs" / "eval" / "act_pick_cube" / "trials.jsonl"
    assert count_trials(path) == 0
    append_trial(path, {"trial": 1, "success": True})
    append_trial(path, {"trial": 2, "success": False})
    lines = path.read_text().splitlines()
    assert [json.loads(line)["trial"] for line in lines] == [1, 2]
    assert count_trials(path) == 2
