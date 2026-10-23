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


def test_stages_are_the_76_protocol_ones() -> None:
    # "Score each trial on stages (reach, grasp, lift, over the bin, released
    # in the bin)" (#76, eval protocol), plus none for no stage reached.
    assert STAGES == (
        "none",
        "reach",
        "grasp",
        "lift",
        "over the bin",
        "released in the bin",
    )


def test_the_success_prompt_is_the_76_definition() -> None:
    ask = Answers("y", "", "")
    ask_score(ask)
    assert (
        "the cube ends up inside the bin and released, within 30 s, with no "
        "human touch, and the arm stops without hitting the bin or table hard "
        "enough to move them"
    ) in ask.prompts[0]


def test_a_success_is_scored_as_released_in_the_bin() -> None:
    ask = Answers("y", "2", "clean")
    assert ask_score(ask) == Score(
        success=True, stage="released in the bin", start_position="2", notes="clean"
    )
    assert len(ask.prompts) == 3


def test_a_fail_asks_for_the_furthest_stage_by_name() -> None:
    ask = Answers("n", "over the bin", "", "on the rim")
    assert ask_score(ask) == Score(
        success=False, stage="over the bin", start_position="", notes="on the rim"
    )


def test_a_stage_can_be_given_by_number() -> None:
    ask = Answers("n", "3", "", "")
    assert ask_score(ask).stage == "lift"
    assert "3 lift" in ask.prompts[1]


def test_a_fail_can_still_reach_the_last_stage() -> None:
    # A touch or an Escape is a fail even when the cube was released.
    ask = Answers("n", "5", "", "touched")
    assert ask_score(ask).stage == "released in the bin"


def test_bad_answers_are_asked_again() -> None:
    ask = Answers("maybe", "N", "place", "6", "GRASP", "4", "")
    score = ask_score(ask)
    assert score.success is False
    assert score.stage == "grasp"
    assert len(ask.prompts) == 7


def test_end_of_input_is_not_scored() -> None:
    with pytest.raises(EOFError):
        ask_score(Answers("n"))


def test_record_fields() -> None:
    now = datetime(2026, 11, 2, 14, 30, 5, tzinfo=UTC)
    record = trial_record(
        Score(success=False, stage="lift", start_position="1", notes=""),
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
        "stage": "lift",
        "start_position": "1",
        "notes": "",
        "policy": "/p",
        "device": "mps",
    }


def test_records_append_one_json_line_each(tmp_path: Path) -> None:
    path = trials_path(tmp_path, "act_pick_cube", "last")
    assert (
        path
        == tmp_path / "outputs" / "eval" / "act_pick_cube" / "last" / "trials.jsonl"
    )
    assert (
        trials_path(tmp_path, "run", "")
        == tmp_path / "outputs" / "eval" / "run" / "trials.jsonl"
    )
    assert count_trials(path) == 0
    append_trial(path, {"trial": 1, "success": True})
    append_trial(path, {"trial": 2, "success": False})
    lines = path.read_text().splitlines()
    assert [json.loads(line)["trial"] for line in lines] == [1, 2]
    assert count_trials(path) == 2
