# Decisions

One line each, newest first. Format: `YYYY-MM-DD · chose X over Y · reason`.

- 2026-10-22 · chose to leave LeRobot out of the dependencies over adding it at setup · it comes in with the first project that needs it, pinned in that project's `pyproject.toml`, so its version is chosen for a real use.
- 2026-10-22 · chose Git LFS for CAD binaries (STL, STEP, 3MF) over committing them directly · they are large and change as whole files, and LFS keeps the git history small.
- 2026-10-22 · chose one uv workspace monorepo over one repo per project · projects share arm code, calibration files and hardware files, and one place keeps them consistent with a single lock file.
