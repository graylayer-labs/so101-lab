"""The control rate of one rollout episode, from LeRobot's own output.

Paths are relative to ``site-packages/lerobot`` (0.6.1).

LeRobot prints nothing per control step except when a step is late. In the
episodic policy loop (rollout/strategies/episodic.py L222-256) each step
times its own work, ``dt``, and sleeps ``1 / fps - dt``; when that is
negative it logs, at L248-254::

    Record loop is running slower ({1 / dt:.1f} Hz) than the target FPS
    ({fps} Hz). Dataset frames might be dropped ...

and does not sleep. So a late step lasts ``1 / hz`` as printed, and every
other step lasts ``1 / fps`` (``precise_sleep`` fills the rest, L255). With
``frames`` steps in the episode (a step adds a dataset frame once the policy
returns an action, L239-242) of which ``n`` were late, the episode lasted

    sum(1 / hz_i for the late steps) + (frames - n) / fps

and the mean rate is ``frames`` over that. ``frames`` is the episode's
length from the dataset's ``meta/info.json``. The line goes through
LeRobot's console handler (``init_logging``, utils/utils.py L63-72, called
at scripts/lerobot_rollout.py L205) at WARNING, above its INFO level, so it
always reaches the output.

Limits: a left-arrow re-record drops the episode's frames but not its log
lines; when there are more late steps than frames, the late steps alone give
the rate. The print rounds to 0.1 Hz.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass

LOW_HZ = 25.0
_SLOW_STEP = re.compile(
    r"Record loop is running slower \((?P<hz>[0-9.]+) Hz\) than the target FPS"
)


@dataclass(frozen=True)
class ControlRate:
    hz: float | None  # mean over the episode; None without a frame count
    frames: int | None
    slow_steps: int
    slowest_step_hz: float | None
    target_fps: int

    @property
    def low(self) -> bool:
        """Below about 25 Hz, the rate #76 asks to note with the result."""
        return self.hz is not None and self.hz < LOW_HZ


def slow_step_hz(line: str) -> float | None:
    """The rate in one of LeRobot's late-step warnings, or None."""
    match = _SLOW_STEP.search(line)
    if match is None:
        return None
    try:
        hz = float(match["hz"])
    except ValueError:
        return None
    return hz if hz > 0 else None


def measure(lines: Iterable[str], *, frames: int | None, fps: int) -> ControlRate:
    """The episode's mean control rate from its output and frame count."""
    slow = [hz for hz in map(slow_step_hz, lines) if hz is not None]
    mean: float | None = None
    if frames is not None and frames > 0:
        if len(slow) >= frames:
            mean = len(slow) / sum(1 / hz for hz in slow)
        else:
            seconds = sum(1 / hz for hz in slow) + (frames - len(slow)) / fps
            mean = frames / seconds
    return ControlRate(
        hz=mean,
        frames=frames,
        slow_steps=len(slow),
        slowest_step_hz=min(slow) if slow else None,
        target_fps=fps,
    )
