# Decisions

One line each, newest first. Format: `YYYY-MM-DD · chose X over Y · reason`.

- 2026-10-26 · chose to record the ACT dataset with the one camera we have over buying a fixed camera first · the owner chose to work with what we have. The camera stays on the wrist for now; each episode starts with the wrist bent so it sees the table. When a fixed mount exists, the same camera moves there and is renamed `front` in `configs/local.yaml`, recorded into a separate dataset, so wrist and fixed episodes never mix (their image keys differ). A second camera (about EUR 20-30) only if both score badly. The pre-registered success rate in #76 is lowered to match before any training (#89).
- 2026-10-22 · chose `lerobot[feetech]==0.6.1` pinned in `projects/hw-setup` over an unpinned or range dependency · LeRobot's CLI and calibration format change between releases, so an exact pin keeps calibration files and tools consistent; 0.6.1 needs Python >=3.12 and torch >=2.7,<2.12, which the workspace already allows.
- 2026-10-22 · chose to leave LeRobot out of the dependencies over adding it at setup · it comes in with the first project that needs it, pinned in that project's `pyproject.toml`, so its version is chosen for a real use.
- 2026-10-22 · chose Git LFS for CAD binaries (STL, STEP, 3MF) over committing them directly · they are large and change as whole files, and LFS keeps the git history small.
- 2026-10-22 · chose one uv workspace monorepo over one repo per project · projects share arm code, calibration files and hardware files, and one place keeps them consistent with a single lock file.
