# so101-lab

A uv workspace for SO-101 arm projects (LeRobot, Feetech STS3215 servos,
leader + follower arms).

## Layout

- `shared/so101/`: package `so101`, code used by more than one project.
- `projects/<name>/`: one workspace package per project (`src/`, `tests/`,
  `configs/`, `README.md`). New projects start as a copy of
  `projects/_template/`, which is excluded from the workspace, ty and pytest.
- `hardware/`: calibration JSON, URDF, CAD, `bom.md`.
- `configs/`: machine config. `local.yaml` is gitignored.
- `scripts/`: thin wrappers around LeRobot CLIs.
- `docs/`: `progress.md` (newest first), `setup.md`, `decisions.md`.

## Where new files go

- Code needed by one project stays in that project. Move it to `shared/so101/`
  only when a second project needs it.
- Projects depend on `so101` through the workspace:
  `[tool.uv.sources] so101 = { workspace = true }`.
- Hardware files (calibration, URDF, meshes, CAD) go under `hardware/`, never
  in `src/`. CAD binaries go through Git LFS.
- Project run configs go in `projects/<name>/configs/`; machine settings in
  the root `configs/`.
- Outputs, recordings and datasets never go in the repo (`outputs/`, `/data`
  and `*.mp4` are ignored).
- Third-party dependencies go in the project that needs them:
  `uv add --package <name> <dep>`.

## Commands

```bash
uv sync --dev --all-packages
uv run pytest
uv run pytest --cov   # line and branch coverage per module
uv run ruff check .
uv run ruff format --check .
uv run ty check
```

Tests first for anything under `src/`. Add an entry to `docs/progress.md`
for each finished task.
