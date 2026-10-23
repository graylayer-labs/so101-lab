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
- Done: `so101-eval` (gated `lerobot-rollout`, trial log, `--dry-run`);
  tested with fakes and a 4-step CPU checkpoint, not yet run on the arm (#81).
- Doing: the 1,000-step smoke run on the M4, once the #78 dataset exists.
- Next: train on the task dataset (#80), then run the 10 trials (#82).

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
- Nothing goes to the Hub (`--policy.push_to_hub=false`) or W&B, and
  `lerobot-train` runs with `HF_HUB_OFFLINE=1`, so a dataset with missing
  `data/` or `videos/` fails instead of being looked up on the Hub.
- **A real run needs network access once.** ACT starts from ResNet-18
  ImageNet weights, which torchvision downloads from download.pytorch.org;
  `HF_HUB_OFFLINE` does not stop that. The first smoke run on the laptop and
  every fresh cloud box need network access, or a pre-filled
  `~/.cache/torch/hub/checkpoints/`.
- Each run gets a new folder, `outputs/train/<UTC time>_<dataset name>/`:
  `dataset.json` (the dataset's repo id, root, episodes, frames, fps and
  camera features, for `so101-eval` to check against) and `lerobot/`, which
  `lerobot-train` writes (checkpoints under `lerobot/checkpoints/`).
- **Report steps/s with the decode backend.** `dataset.json` records
  `decode_backend`: `torchcodec` if it loads, else `pyav` (on this Mac
  torchcodec finds no FFmpeg libraries, so it is `pyav`). Video decoding is
  part of each step, so write the backend next to any steps/s figure, and
  compare LeRobot's `data_s` with `updt_s` in the log to see which one limits.

## Evaluate a policy

```bash
uv run so101-eval --policy outputs/train/<run>/checkpoints/last/pretrained_model \
    --task "Pick the cube and place it in the bin" --episodes 10 \
    --dry-run                            # check everything, print the command
uv run so101-eval --policy ... --task "..." --episodes 10
uv run so101-eval --policy ... --task "..." --episodes 5 --resume   # more trials
```

Each trial is one `lerobot-rollout --strategy.type=episodic` run of one
episode. Only the follower is used: LeRobot's episodic rollout needs no
teleop, and without one it drives the follower back to the pose it started
in after the episode. Before every trial you type `y` to confirm the
follower is at its rest pose; after it you score it:

- success or fail, as defined in #76: success is "the cube ends up inside
  the bin and released, within 30 s, with no human touch, and the arm stops
  without hitting the bin or table hard enough to move them";
- for a fail, the furthest of #76's stages reached, by number or name:
  `0 none`, `1 reach`, `2 grasp`, `3 lift`, `4 over the bin`,
  `5 released in the bin` (a success is always `released in the bin`);
- the start position and a note on the failure mode, both optional.

Each score is appended at once to `outputs/eval/<run>/<checkpoint>/trials.jsonl`, one
JSON object per line: `trial`, `episode_index`, `time_utc`, `success`,
`stage`, `start_position`, `notes`, then the run's settings (`policy`,
`checkpoint`, `task`, `device`, `fps`, `episode_time_s`,
`max_relative_target`, `dataset_repo_id`, `dataset_root`), then the
measured control rate (`control_hz`, `frames`, `slow_steps`,
`slowest_step_hz`) and `rollout_log`, the trial's saved output. `<run>` is the
training run's folder name, the one above `checkpoints/`. The eval videos go
to a local LeRobot dataset, `$HF_LEROBOT_HOME/local/rollout_<run>_<checkpoint>` by
default; the first trial creates it and later ones add to it.

Checks before anything runs, also with `--dry-run`; any failure exits 1:

- The follower's calibration passes. The leader's is not needed.
- `--policy` is a folder with `config.json`, `model.safetensors` and
  `train_config.json`, and LeRobot loads `config.json` as a policy config.
- The training dataset's `meta/info.json` can be read: `dataset.root` from
  `train_config.json`, or `$HF_LEROBOT_HOME/<repo_id>`, or
  `--train-dataset PATH`.
- The cameras in `configs/local.yaml` match the policy's image inputs and
  the training dataset: the same names, width x height and fps.
- The device is available. `--device auto` (the default) picks cuda, then
  mps, then cpu. On mps a warning gives the control-rate risk: a published
  SO-101 ACT eval ran at about 15 Hz on an M4 with 40% success, against
  30 Hz and 90% on CUDA for the same checkpoint.
- The dataset root follows `so101-record`'s rules: outside the workspace,
  new unless `--resume`, never half-written. Names must start with
  `rollout_` (LeRobot refuses others, but only after the robot connects).

**Control rate.** The rollout's output is shown as it runs and also saved to
`outputs/eval/<run>/<checkpoint>/logs/trial-<n>.log`. LeRobot prints one line for each
late control step, `Record loop is running slower (<hz> Hz) than the target
FPS (<fps> Hz)` (`lerobot/rollout/strategies/episodic.py` L249-254), and
nothing for the others, which take exactly `1/fps`. With the episode's frame
count from the eval dataset, that gives the mean rate:
`frames / (sum of 1/hz over late steps + other steps / fps)`. It is printed
after each trial and written as `control_hz`. Below 25 Hz a warning asks you
to note it with the result (#76) and do one diagnostic rerun with
`--device cpu` or without `--display` (#82).

`--dataset.push_to_hub=false` is always passed. `--max-step` caps each
follower move as in `so101-teleop` (default 5). The fps is the training
dataset's. Each trial's time limit is `--episode-time-s`, by default #76's
30 s. Optional: `--repo-id`, `--dataset-root`, `--reset-time-s`
(after a left-arrow re-record), `--device`, `--display`, `--config`.

The follower's start pose is not checked by a reading: the repo defines no
safe pose, and the leader is not connected to compare with. LeRobot holds
the pose it starts from as "home", so start each trial at the rest pose.

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
