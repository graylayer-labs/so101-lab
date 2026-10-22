# so101-lab

Projects and shared code for a LeRobot SO-101 robot arm pair: a leader arm
moved by hand and a follower arm that copies it, both driven by Feetech
STS3215 servos. Each project lives in its own folder, and the code and
hardware files they share live here once.

The arm is a platform for many small experiments (teleoperation, data
collection, policy training). Keeping them in one repo means calibration,
arm config and hardware notes are written once and every project uses the
same version.

## Where it's at (2026-10-22)

- Done: uv workspace with a shared `so101` package and a copyable project
  template.
- Done: the machine config loader (#35), LeRobot 0.6.1 pinned in `hw-setup`
  (#38) and calibration sanity checks (#36).
- Doing: the repo standard (#40, #12) and test coverage (#41).
- Next: arm bring-up scripts (#11, #13-#18) and the setup runbook (#27).
- Hardware: both arms have a first calibration (#39); parts, assembly and
  servo IDs are owner steps (#29-#31).

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
| `scripts/` | Planned setup scripts around the LeRobot CLIs. |
| `docs/progress.md` | What changed, newest first. |
| `docs/setup.md` | Assembly and software setup checklist. |
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
