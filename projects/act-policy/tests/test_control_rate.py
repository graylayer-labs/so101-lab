"""Control rate from lerobot-rollout's own log lines."""

from collections.abc import Callable

import pytest

from act_policy.control_rate import ControlRate, measure, slow_step_hz

SlowLine = Callable[..., str]  # the conftest fixture


OTHER = [
    "INFO 2026-11-02 14:30:01 _rollout.py:219 Building rollout context...",
    "INFO 2026-11-02 14:30:04 ls/utils.py:147 Recording episode 0",
]


def test_slow_step_lines_are_parsed(slow_line: SlowLine) -> None:
    assert slow_step_hz(slow_line(14.8)) == 14.8
    assert slow_step_hz(OTHER[0]) is None
    assert slow_step_hz(slow_line(14.8) + "\n") == 14.8


def test_no_slow_steps_means_the_target_rate() -> None:
    rate = measure(OTHER, frames=900, fps=30)
    assert rate == ControlRate(
        hz=30.0, frames=900, slow_steps=0, slowest_step_hz=None, target_fps=30
    )


def test_slow_steps_lower_the_mean(slow_line: SlowLine) -> None:
    # 3 steps at 15 Hz (0.2 s) and 7 on time at 30 Hz (7/30 s): 10 frames in
    # 13/30 s, so 300/13 Hz.
    lines = [*OTHER, slow_line(15.0), slow_line(15.0), slow_line(15.0)]
    rate = measure(lines, frames=10, fps=30)
    assert rate.hz == pytest.approx(300 / 13)
    assert rate.slow_steps == 3
    assert rate.slowest_step_hz == 15.0


def test_every_step_slow(slow_line: SlowLine) -> None:
    lines = [slow_line(12.0), slow_line(16.0)] * 5
    rate = measure(lines, frames=10, fps=30)
    assert rate.hz == pytest.approx(10 / (5 / 12 + 5 / 16))
    assert rate.slowest_step_hz == 12.0


def test_without_frames_there_is_no_mean(slow_line: SlowLine) -> None:
    rate = measure([slow_line(14.0)], frames=None, fps=30)
    assert rate.hz is None
    assert rate.slow_steps == 1
    assert rate.slowest_step_hz == 14.0


def test_more_slow_lines_than_frames_uses_the_slow_steps_alone(
    slow_line: SlowLine,
) -> None:
    # A left-arrow re-record drops the frames but not the log lines.
    lines = [slow_line(20.0)] * 4
    rate = measure(lines, frames=2, fps=30)
    assert rate.hz == pytest.approx(20.0)


@pytest.mark.parametrize(("hz", "low"), [(24.9, True), (25.0, False), (None, False)])
def test_low_is_below_25_hz(hz: float | None, low: bool) -> None:
    rate = ControlRate(
        hz=hz, frames=1, slow_steps=0, slowest_step_hz=None, target_fps=30
    )
    assert rate.low is low
