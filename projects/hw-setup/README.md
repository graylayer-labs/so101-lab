# hw-setup

Gets the SO-101 arms ready for use: finds their serial ports, sets motor IDs
and calibrates them with LeRobot's tools, run from this workspace.

## Goal

LeRobot is installed in the workspace and the arm tools run from it.

## Expected results

`uv run lerobot-calibrate --help` exits 0. Success is exit code 0; failure is
any import or install error.

## Status (2026-10-22)

- Done: `lerobot[feetech]==0.6.1` pinned and installed.
- Doing: nothing.
- Next: find the ports and set motor IDs (needs hardware).

## Layout

- `src/hw_setup/`: the code.
- `tests/`: tests for it.
- `configs/`: run configs for this project. Machine settings (ports, cameras)
  stay in the root `configs/`.

## Run

```bash
uv sync --dev --all-packages
uv run pytest projects/hw-setup
```
