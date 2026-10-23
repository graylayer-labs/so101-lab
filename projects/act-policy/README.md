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

- Done: `so101-train` builds and runs the `lerobot-train` command (#79),
  tested through LeRobot's own parser and a 4-step CPU run.
- Doing: the 1,000-step smoke run on the M4, once the #78 dataset exists.
- Next: `so101-eval` (#81).

## Train

```bash
uv run so101-train --repo-id local/so101_pick_cube_<stamp> --smoke --dry-run
uv run so101-train --repo-id local/so101_pick_cube_<stamp> --smoke
```

- `--dry-run` prints the dataset, device, settings, run folder and the exact
  `lerobot-train` command, and creates and runs nothing.
- The dataset root defaults to `$HF_LEROBOT_HOME/<repo-id>`; pass
  `--dataset-root` for another folder. It is read from local files only: a
  dataset with missing metadata is refused, since LeRobot would fetch it
  from the Hub.
- Settings come from `configs/act_pick_cube.yaml`: the full run is
  LeRobot's 100,000 steps at batch 8, saving every 10,000; `--smoke` is
  1,000 steps with one checkpoint at the end. `--steps`, `--batch-size` and
  `--config` override them.
- The device is cuda (with AMP), then mps, then cpu. `--device` picks one,
  and is refused if it is not available.
- Nothing goes to the Hub (`--policy.push_to_hub=false`) or W&B.
- Each run gets a new folder, `outputs/train/<UTC time>_<dataset name>/`:
  `dataset.json` (the dataset's repo id, root, episodes, frames, fps and
  camera features, for `so101-eval` to check against) and `lerobot/`, which
  `lerobot-train` writes (checkpoints under `lerobot/checkpoints/`).

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
