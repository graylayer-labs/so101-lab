# so101-lab

Projects and shared code for a LeRobot SO-101 robot arm pair: a leader arm
moved by hand and a follower arm that copies it, both driven by Feetech
STS3215 servos. Each project lives in its own folder, and the code and
hardware files they share live here once.

The arm is a platform for many small experiments (teleoperation, data
collection, policy training). Keeping them in one repo means calibration,
arm config and hardware notes are written once and every project uses the
same version.

## Where it's at (2026-10-23)

- Done: the bring-up tools (#13-#18), teleop safety (#63, #64: a 5° per-update cap and a read-only `so101-align` check), the BOM and the runbook [`docs/setup.md`](docs/setup.md). Tested with fakes only.
- Done: both arms assembled, given IDs and calibrated with LeRobot directly (#30, #44). Teleop worked only through a temporary controller, because the two calibrations disagree by about 10° at the elbow.
- Doing: the full setup on the real arms (#65, #66, #31, #32, #33): real ports, camera, a matched recalibration, `so101-teleop`, a first dataset.
- Doing: Phase 2 tooling in [`projects/act-policy`](projects/act-policy): `so101-train` (#79) and `so101-eval` (#81) for ACT (#68).
- Next: record 50 episodes, train ACT, score 10 trials against the pre-registered 5/10 (#76-#83); then SmolVLA (#69).

## Pipeline

Skip: this repo holds many separate projects; each project's README carries
its own goal, expected results and status.

## Results so far

| Claim | Number | Link |
|---|---|---|
| No results yet | - | - |

## How to read this repo

| Path | What it holds |
|---|---|
| `shared/so101/` | Code reused across projects: joint names, arm config, calibration loading. |
| `projects/` | One folder per project; `projects/_template/` is the skeleton to copy. |
| `hardware/` | Calibration JSON, URDF, CAD and the bill of materials. |
| `configs/` | Machine config (ports, cameras): `example.yaml` committed, `local.yaml` not. |
| `scripts/` | Reserved for thin wrappers around the LeRobot CLIs; holds only a README. The `so101-*` commands live in `projects/hw-setup`. |
| `docs/progress.md` | What changed, newest first. |
| `docs/setup.md` | The runbook: unboxing to the first recorded dataset, one script per step. |
| `docs/decisions.md` | One line per decision and its reason. |

## Setup

Requires Python 3.12 or later and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --dev --all-packages
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run ty check
```

CAD files are stored with Git LFS: run `git lfs install` once before adding
any.

LeRobot is not a dependency yet. It comes in with the first project that
needs it, pinned in that project's `pyproject.toml`.

## Starting a new project

Copy `projects/_template/` to `projects/<name>/`, rename the package, and
fill in its README's Goal and Expected results before writing code. Steps in
[projects/README.md](projects/README.md).

## Licence

MIT. See [LICENSE](LICENSE).
