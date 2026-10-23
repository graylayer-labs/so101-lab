# act-policy

Phase 2 of so101-lab (epic #68): train an ACT policy on a local LeRobot
dataset recorded with `so101-record`, then run it on the follower arm.

## Goal

A learned ACT policy does one simple task on the follower, trained from the
repo with flags we trust: local data only, nothing pushed to the Hub.

## Expected results

- A 1,000-step smoke run on the M4 (MPS) finishes in well under the 2 h
  laptop limit. Estimate, not measured: 0.7-1.5 steps/s, so 11-24 min.
- The training loss falls over the smoke run and a checkpoint is written
  under `outputs/train/`.
- A full 100k-step run does not fit on the laptop (about 20-40 h at the
  estimate); it goes to one cloud GPU.

## Status (2026-10-23)

- Done: project created.
- Doing: `so101-train` (#79).
- Next: `so101-eval` (#81).

## Layout

- `src/act_policy/`: the code.
- `tests/`: tests for it.
- `configs/`: run configs for this project. Machine settings (ports, cameras)
  stay in the root `configs/`.

## Run

```bash
uv sync --dev --all-packages
uv run pytest projects/act-policy
```
