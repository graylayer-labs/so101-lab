# Progress

Newest first. One entry per merged task or chunk.

## 2026-10-26 · A training plan that works with no GPU quota

Every AWS GPU quota is 0, so the 100k-step cloud run (#80) cannot start.
Research and aws-manager's review found a route that needs no GPU: train
ACT on the laptop to 20k-30k steps in resumed runs of 2 h or less, and
build the SageMaker route alongside for when a quota arrives. The plan,
with two diagrams, is [`docs/training-plan.md`](training-plan.md).

| Claim | Number | Where |
|---|---|---|
| Steps where ACT reached 10/10 elsewhere (30 SO-101 episodes, M2 Mac) | 20k | [classmethod](https://dev.classmethod.jp/articles/so-arm101-duck-pick-imitation-learning-mac-training/) |
| Laptop steps per 2 h run (estimate) | about 9k-14k | `docs/training-plan.md` |
| SageMaker g5.xlarge spot, 100k steps (estimate) | about EUR 2-3 | same |
| GPU quotas above 0 | none | aws-manager review in #101 |

![From demos to a scored policy](figures/2026-10-26-act-pipeline.png)

### What we learned

**A first ACT does not need 100k steps.** One SO-101 report scored 10/10
at 20k steps and 9/10 at 30k, so the laptop can get there in 2-3 runs.

**The free SageMaker GPU is gone.** Studio Lab stopped taking new sign-ups
in July 2026, and notebook GPUs need their own quotas, which are 0 as well.

## 2026-10-26 · The arms recorded a first dataset that LeRobot can load

With the owner driving the leader, `so101-record` saved 5 episodes of one
task, "Pick up the block and place it in the plant pot", with the wrist
camera. This is the first real data the ACT training tools can read, so the
whole path from arms to dataset now works end to end.

| Claim | Number | Where |
|---|---|---|
| Episodes, frames | 5, 4,500 at 30 fps (pre-registered: 2,000-3,000, at 15-20 s each) | `outputs/hw/dataset-summary.json` (local) |
| Loads with `LeRobotDataset` | yes: state and action (6 joints), wrist image 640x480 | same |
| Size on disk | 18 MB, outside the repo | `~/.cache/huggingface/lerobot/graylayer/so101-first` |
| Largest leader-follower gap before recording | 2.5° (elbow_flex; limit 5°), printed by `so101-record`, which does not save it; 3.0° in the last saved check 15 min earlier | `outputs/hw/alignment-20261026T143039Z.json` (local) |
| `so101-doctor --open-cameras` | nothing failed | `outputs/hw/doctor-20261026T143345Z.txt` (local) |
| Episodes where the block reached the pot | 4 of 5 (episode 1 still held it at 30 s) | wrist video, checked by eye |

![The wrist camera 20 s into each episode](figures/2026-10-26-first-dataset-grasps.jpg)

The wrist camera 20 s into each of the five episodes: the block sits
between the jaws, and in two frames the pot is behind it.

### What we learned

**Frames came out above the forecast because no episode ended early.** The
right arrow key should end an episode, but the terminal had no macOS
Accessibility permission, so every episode ran its full 30 s. That
permission is now in `docs/setup.md`.

**The follower runs 12 V servos.** The parts list assumed 5 V for both arms.
Reading the servos' own voltage limit settled it: 14.0 V on all six follower
servos, so they are the 12 V variant on a 12 V supply. The leader stays on
5 V. `hardware/bom.md` records it.

**A quiet start is not a hang.** LeRobot prints nothing for about 25 s while
it loads, and the follower holds still while the dataset is saved at the
end. Both looked like faults the first time.

**The wrist camera points at the ceiling at rest.** It sees the grasp well
but not the table until the arm reaches down. Decided (#89): keep the one
camera, start each episode with the wrist bent so it sees the table, and
move it to a fixed mount later as a separate dataset.

Replaying an episode in simulation, also asked for in #33, moved to #24.

## 2026-10-24 · The follower now copies the leader with no snap at start

Both arms were recalibrated with `so101-calibrate` from the same pose, so
the same physical pose now reads as the same numbers on both. Before, the
wrist roll read half a turn apart and the elbow 13° apart, which is why the
follower jumped when teleop started. After, `so101-teleop` ran on the real
arms with no snap, first without the camera and then with the wrist camera
live in the viewer.

| Claim | Number | Where |
|---|---|---|
| Gap before, wrist_roll | 174.3° | `outputs/hw/alignment-before.json` (local) |
| Gap before, elbow_flex | 13.1° (expected 10-13°) | same |
| Largest gap after | 3.7° (shoulder_pan; limit 5°) | `outputs/hw/alignment-after.json` (local) |
| Largest gap the next day, after a power cycle | 2.5° | `outputs/hw/alignment-20261024T164739Z.json` (local) |
| Wrist camera | 640x480 at 30 fps, measured | `configs/local.yaml` (local) |
| `so101-align` on the real arms | refused at 174° before, passed at 3.7° after | the two files above |
| `so101-doctor --open-cameras` | nothing failed, both ports and the wrist camera | `outputs/hw/doctor-20261024.txt` (local) |

**Ports.** Found with the same unplug test `so101-find-ports` uses (unplug
the leader; the port that vanishes is the leader's), done by hand because
the agent's shell cannot answer the script's ENTER prompts. Both
are `/dev/cu.usbmodem*` names, kept in the gitignored `configs/local.yaml`.

**Camera.** One wrist camera on the follower's gripper (`USB2.0_CAM1`),
shown live in `so101-teleop --display` after the Rerun viewer was added
(LeRobot's `viz` extra, now a dependency) and the lens refocused by hand.

### What we learned

**The wrist-roll zero comes from the middle pose.** LeRobot sets each
joint's zero from the pose you hold when you press ENTER, and it never
sweeps the wrist roll. So both arms must be in the same middle pose, wrist
rotated the same way, or they disagree by whatever the two wrists differed.

**macOS camera permission had to be asked for, not reset.** OpenCV only
checks the permission and never asks, so no prompt appears. A short Swift
call to `AVCaptureDevice.requestAccess` brought the prompt up. The steps are
in the `so101-arm-init` skill.

**Camera indices move.** With the wrist camera unplugged, the MacBook camera
takes index 0 and `so101-doctor --open-cameras` still passes.

## 2026-10-23 · A trained policy can be run on the follower and each trial scored

`so101-eval` runs a checkpoint on the follower with LeRobot's
`lerobot-rollout`, one episode per trial. Before the arm moves it checks the
follower's calibration, the checkpoint, and that the cameras match what the
policy was trained on in name, size and fps. After each trial it asks for a
score, against #76's success definition and stages, and appends it to
`outputs/eval/<run>/<checkpoint>/trials.jsonl` with the control rate measured from
LeRobot's own output. It is tested with fakes only; no policy has run on the
arm yet, so no real control rate has been measured (#81).

| Claim | Number | Where |
|---|---|---|
| Leader needed for evaluation | no | `lerobot/rollout/configs.py` L225, L276-277 |
| Push to the Hub | always off | `act_policy/rollout_argv.py` |
| Camera checks | names, width x height, fps | `act_policy/policy_check.py` |
| Default movement cap | 5 per update | `--max-step`, as `so101-teleop` |
| Control rate warning | below 25 Hz | `act_policy/control_rate.py` |
| Verified on the real arm | not yet | #81, #82 |

### What was tried, and what we learned

**`lerobot-rollout` needs no leader.** Only its DAgger mode requires a
teleop. Without one, episodic mode drives the follower back to the pose it
had when it connected, so that pose acts as "home". The wrapper asks you to
confirm the follower is at its rest pose before each trial.

**Rollout datasets must be named `rollout_*`, not `eval_*`.** The plan said
`eval_`, the prefix `lerobot-record` keeps for policy runs. In 0.6.1 `lerobot-rollout` refuses any other
name, but only after it has loaded the policy and connected the robot, so
the wrapper checks the name first.

**LeRobot does not check camera size or fps.** It refuses camera names only
when neither set contains the other. A resized or slower camera would run
and quietly degrade ACT, so the wrapper compares `configs/local.yaml` with
the policy and its training dataset's `meta/info.json`.

**One rollout per trial.** LeRobot owns the keyboard while it runs, so the
only way to score each episode as it ends is to run one episode at a time,
resuming the same eval dataset. The cost is loading the model again for each
trial.

**LeRobot only prints the late control steps.** Each late step logs its own
rate, `Record loop is running slower (14.8 Hz) ...`, and skips its sleep;
every other step sleeps to about `1/fps` (the little work after the
sleep is not counted). So the late lines plus the
episode's frame count give the mean rate without changing LeRobot. The
wrapper tees the output to the terminal, keeps it per trial, and writes the
rate into each trial's line.

**A policy type has to be registered before LeRobot can read its config.**
The tests passed, because the fixture imports `ACTConfig`, while the real
command failed with "Policy type 'act' is not registered". A test in a fresh
interpreter now catches it.

## 2026-10-23 · ACT can be trained from the repo with flags we trust

`so101-train` (new project `projects/act-policy/`) builds and runs the
`lerobot-train` command for ACT on a local dataset. It never pushes to the
Hub, keeps W&B off, always passes the dataset root, and gives each run a new
folder `outputs/train/<UTC time>_<dataset>/` with the dataset's own metadata
in `dataset.json`. `--dry-run` prints the command and runs nothing; `--smoke`
is a 1,000-step laptop run. Nothing has trained on the real dataset yet: the
M4 steps/s is still an estimate until the #78 dataset exists.

| Claim | Number | Where |
|---|---|---|
| Real `lerobot-train` run in the tests, CPU, tiny ACT | 4 steps, 2.4 s | `test_a_real_cpu_micro_train` |
| Flags checked by LeRobot's own parser and `validate()` | 13 (12 always passed, plus `use_amp` on cuda) | `tests/test_train.py` |
| Network connections in the test process | 0 (socket guard) | `tests/conftest.py` |
| Network in the micro-train's `lerobot-train` child | none needed: the test passed under `sandbox-exec` with all outbound IP denied (reviewer's check) | `test_a_real_cpu_micro_train` |
| Smoke run length | 1,000 steps | `configs/act_pick_cube.yaml` |
| M4 steps/s | not measured yet (estimate 0.7-1.5) | #79 |

### What was tried, and what we learned

**Two LeRobot defaults would stop or leak a run.** `policy.push_to_hub`
defaults to True, and with no `policy.repo_id` training fails at start. A
dataset folder with missing metadata makes LeRobot download `meta/` from the
Hub. So the push flag is always false, and a dataset with gaps is refused
before LeRobot sees it.

**`lerobot-train` refuses an output folder that already exists.** The tool
wants to write the dataset's metadata before training starts, so it creates
the run folder, writes `dataset.json`, and points `--output_dir` at a
`lerobot/` folder inside it that LeRobot then creates.

**Training needs LeRobot's `training` extra.** Without `accelerate` the run
stops at start. The project adds `lerobot[dataset,training]==0.6.1`: the same
pin as hw-setup, one version in the lock.

**A real training run fits in a unit test.** With no pretrained backbone
(that would download ResNet-18 weights), a tiny transformer and a 16-frame
image dataset, 4 steps on CPU take about 2.4 s, so the test runs by default.
It uses images, not video, so video decoding is first exercised by the
smoke run. Here torchcodec cannot load (no FFmpeg libraries) and LeRobot
decodes with pyav; `dataset.json` records the backend, and the measured
steps/s should be reported with it.

**`HF_HUB_OFFLINE` covers the Hub, not torchvision.** `lerobot-train` runs
offline, but a real run still downloads the ResNet-18 weights from
download.pytorch.org the first time.

## 2026-10-23 · Teleop now caps each follower move and checks the arms match first

On 2026-10-22 the follower lurched towards the leader at the start of
teleop: the two arms read about 10-13° apart at elbow_flex and about 98° at
wrist_roll. `so101-teleop` and `so101-record` now refuse to start until every
joint of the two arms is within 5°, and every command they build caps each
follower move at 5° per update. `so101-align --watch` shows the gap live
while you pose the arms. Both are tested with fakes only; neither has run on
the real arms yet.

| Claim | Number | Where |
|---|---|---|
| Default movement cap | 5 per update (degrees; % of range for the gripper) | `--max-step`, `hw_setup/teleop.py` |
| Default alignment limit | 5 (same units) | `--align-max`, `hw_setup/align.py` |
| Writes to either arm during the check, in tests | 0 | `tests/test_align.py` |
| Verified on the real arms | not yet | #64 |

### What was tried, and what we learned

**LeRobot's `connect()` is not read-only, even with `calibrate=False`.** The
follower's `connect` always runs `configure()`, which writes motor settings
inside a "torque disabled" block that turns torque back on when it ends. So
the check never calls it. It builds LeRobot's own follower and leader from
the same command line `so101-teleop` runs, then only uses their motor buses
to read positions, and closes the ports without touching torque.

**The cap alone does not stop the jump.** `max_relative_target` limits each
update, not the speed: at 60 updates a second, 5° per update is still 300°
per second, so a 98° gap is crossed in a third of a second. That is why the
alignment check is the real guard, and the cap is the backstop.

**The wrist difference is not wrapped at ±180°.** The follower's wrist is a
position servo over its full raw range, so +179° to -179° is a 358° turn.
Wrapping would have called it 2° and let it through.

**The test fake is LeRobot's real bus with only the serial layer
replaced**, so readings come back through LeRobot's own conversion to
degrees. An earlier bug hid behind a fake that returned the wrong shape.

## 2026-10-23 · so101-find-ports works from any directory and keeps file modes

`so101-find-ports` now finds the workspace with the same helper as the other
commands (`hw_setup.workspace.find_workspace_root`), so it no longer fails
from `~` or `/tmp`. Rewriting `configs/local.yaml` keeps its file mode instead
of leaving it at 0600, and a new file gets 0644 (or the umask default). Using
the same arm for both ports is now reported as soon as the second port is
known, not after both rounds. The hw-setup README status block lists the Done
lines together (#50).

## 2026-10-23 · Odd calibration files get a one-line refusal with the right reason

`so101-teleop` no longer shows a traceback for an unreadable calibration file
(for example `chmod 000`): it names the arm and exits 1. `so101-calibrate`
says the right thing for a directory at `<id>.json` (LeRobot would calibrate,
write the motors, then fail to save), removes a partial backup if closing it
fails, and its dry-run and `--help` text now say that anything other than 'c'
at LeRobot's prompt writes the stored file to the motors, not "keeps the
file". The machine config port error names `cu.*` as well as `tty.*` (#55).

## 2026-10-23 · Moving a gripper span bound by one now fails a test

The calibration check rejects a gripper span outside 300 to 2500. Its fail
fixtures sat at 250 and 3000, so a bound could move without a test noticing.
Two new fixtures, at widths 299 and 2501, trip only the `gripper_span` check.
On a scratch copy, six changes to `GRIPPER_SPAN` each failed a test:
`(301, 2500)`, `(300, 2499)`, `(260, 2500)`, `(300, 2600)`, `(299, 2500)` and
`(300, 2501)`. Tests only; nothing under `src/` changed (#45).

## 2026-10-22 · Every arm bring-up step is now one tested command, with a runbook

The SO-101 arms can now be taken from the box to a first recorded dataset by
following `docs/setup.md`. Each step is a `so101-*` command that checks what it
can before a servo moves, and prints the exact LeRobot command with
`--dry-run`. None of the commands has run on the real arms yet. The committed
calibrations were made with LeRobot directly.

| Claim | Number | Where |
|---|---|---|
| Bring-up commands on main | 6 (find-ports, setup-motors, calibrate, teleop, record, doctor) | `projects/hw-setup/` |
| Tests on main | 268 passing (32 at the start of the shift), none need hardware | `uv run pytest` |
| Line and branch coverage of `src/` at the coverage audit (95% on main now, after the new tools) | 93% before, 100% after | PR #46 |
| PRs merged this shift, each with green CI and a posted review | 18 | #1, #36 to #59 |
| CI time with LeRobot and its dataset extra | about 1 minute | PR #56 checks |
| Real bugs caught by review before merge | 6 | below |

### What was tried, and what we learned

**Every wrapper builds its command from one place.** `hw_setup.lerobot_argv`
turns the machine config into LeRobot's flags. Its tests feed each command
through LeRobot's own config parser, so a misspelt flag fails a test instead
of failing at the arm. Flag names were read from the LeRobot 0.6.1 source,
not only its docs, because `--help` prints over 1,200 lines covering every
robot type.

**Review found real bugs that the tests had missed.** Each one would have hit
the arms or the data:

- A relative repo path would have made LeRobot look in the wrong folder and
  silently start a fresh calibration (#11).
- The calibration diff ignored servo IDs, so swapped IDs looked like "no
  change" (#20).
- `so101-find-ports` wrote `local.yaml` in whatever folder it was run from
  (#13).
- The parts list could be read as putting 12 V on the leader (#28).
- `so101-record --resume` on a partly written dataset could pull a public
  dataset's metadata from the Hugging Face Hub over the local copy (#17).
- `so101-doctor` failed any Mac port written as `/dev/tty.*`, because macOS
  lists only `/dev/cu.*` names. The test's fake port list used `tty.*`, which real pyserial never
  returns (#18).

The lesson from the last one: a fake in a test must copy what the real tool
returns, or it hides exactly the bug it should catch.

**What LeRobot does that its guide does not say.** All of these were read
from the 0.6.1 source and are now handled or documented:

- `lerobot-find-port` has no `--help` and waits for keyboard input.
- LeRobot's camera search opens every index from 0 to 59, which triggers the
  macOS camera prompt. The doctor lists cameras without opening them.
- Pressing ENTER at the calibrate prompt writes the stored file to the
  motors.
- Recording pushes to the Hub by default and adds a timestamp to the dataset
  name.
- LeRobot reports SO-101 configs as `so100_*`.

**Not done.** #12 stays open: the org's shared CI workflow cannot install
every package in a uv workspace, so this repo keeps a local copy with the same
pinned actions until graylayer-labs/.github#33 adds an `all-packages` input.
Small follow-ups are #45, #50 and #55.

### Next

The owner steps #29 to #33 (parts, assembly, calibration, teleop, a first
dataset), following `docs/setup.md`. Start with `so101-doctor`.

## 2026-10-22 · One runbook takes you from the box to the first dataset

`docs/setup.md` now lists every step in order: check the parts and power
supplies, find the ports, set the motor IDs, assemble, calibrate, run the
doctor, teleoperate, record. Each step names its script, says what the
script checks before a servo moves, shows the real `--dry-run` output and
says what to do when it fails. It ends with a quick-reference list of
commands, a troubleshooting table and what has not been tested.

None of the `so101-*` scripts has run on the arms yet (the arms were calibrated outside them, #39); every output is a dry run or an error case
with no arm attached. The sample in the `hw-setup` README no longer carries a
personal device name, and its `tty` example now uses the `cu` name. Issue #27.

## 2026-10-22 · CI reports as checks / checks with pinned actions

The CI check now reports as `checks / checks`, the same name the other org
repos use, and every action is pinned to a full commit SHA with its version
in a comment. Dependabot's existing `github-actions` entry keeps bumping
them. The org's shared Python workflow is not used yet: it syncs without
`--all-packages`, so `projects/hw-setup` and LeRobot would not be installed.
The steps stay in a local `checks.yml` until the shared workflow gains an
input for the sync arguments.

## 2026-10-22 · A doctor command checks the setup before you touch hardware

`uv run so101-doctor` reports PASS, WARN or FAIL for the LeRobot version
(must be the pinned 0.6.1), the machine config, whether each configured serial
port is present, the calibration files and the cameras. Every problem comes
with the command that fixes it. It opens no port and runs no LeRobot, so it is
safe with no arm attached; cameras are only listed unless you pass
`--open-cameras`. Tested with fakes only. Sample output is in
`projects/hw-setup/README.md`.

## 2026-10-22 · Recording a local dataset is one command

`uv run so101-record --task TEXT --repo-id USER/NAME --episodes N` runs
`lerobot-record` with the leader driving the follower, after the same
calibration check as `so101-teleop`. It never pushes to the Hub: it always
passes `--dataset.push_to_hub=false`, which LeRobot otherwise defaults to
true. It needs task text, writes to `$HF_LEROBOT_HOME/USER/NAME` unless
`--dataset-root` says otherwise, and refuses any root inside the workspace.
An existing root is refused unless `--resume` is given, which adds episodes
to it. `--dry-run` prints the plan and the exact command. LeRobot's
`dataset` extra is now installed (21 more packages in the lock), so the tests
parse the command with LeRobot's own `RecordConfig`. Nothing was run on
hardware.

## 2026-10-22 · Recalibrating an arm shows what changed per joint

`uv run so101-calibrate --role leader|follower` runs LeRobot's calibration
and saves the result in `hardware/calibration/<role>/<id>.json`. The old file
is backed up first, the new one is checked for impossible values, and a table
shows each joint whose offset or range changed. If the check fails, it says
where the backup is and how to put it back. `--dry-run` prints the exact
LeRobot command and changes nothing. Tested with a fake LeRobot only; it has
not been run on the real arms yet.

## 2026-10-22 · Teleop starts only with valid calibrations

`uv run so101-teleop` starts `lerobot-teleoperate` for the leader and
follower, with `--no-cameras` and `--display` options. Before anything else
it loads `hardware/calibration/<role>/<id>.json` for both arms (the id comes
from `configs/local.yaml`) and runs the calibration sanity checks. If a file
is missing or fails, it names the arm and the problem and exits 1, also with
`--dry-run`, which otherwise prints the exact command and runs nothing. The
tests use temporary workspaces with copies of the committed calibrations.
Nothing was run on hardware.

## 2026-10-22 · Motor setup is a guided command

`uv run so101-setup-motors --role leader|follower` prints the gripper-first
wiring order, the gear ratio of each joint (checked against `hardware/bom.md`)
and the power warning, asks for confirmation, then runs
`lerobot-setup-motors` for that arm. `--dry-run` prints the same plus the
exact command and runs nothing. The config defaults to
`configs/local.yaml` in the workspace, wherever the command is run from; it
does not fall back to the example. The tests use a fake runner and fake
input. Nothing was run on hardware.

## 2026-10-22 · The bill of materials lists every part, with gearing, voltage and EUR prices

`hardware/bom.md` now shows which gearing each joint of the leader and
follower needs, which servo voltage goes with which power supply (5 V or
12 V), the bus servo adapter board and indicative EUR prices from upstream.
It also explains why a wrong supply can burn out a servo. Parts the owner
still has to confirm are marked with #29. Links: issue #28.

## 2026-10-22 · One command finds the arm ports and fills in `local.yaml`

`uv run so101-find-ports` asks you to unplug and replug the leader and then
the follower arm, works out each arm's serial port from what disappeared, and
writes both to `configs/local.yaml` without touching the other keys. The file
is checked with the machine config validator before it is written, and
`--dry-run` prints the plan and changes nothing. It does not use
`lerobot-find-port`, which waits on the keyboard and saves nothing. Tested
with fake ports and fake key presses only; it has not been run on the real
arms yet.

## 2026-10-22 · Two calibrations can be compared joint by joint

`so101.diff_calibrations` compares two calibrations and lists, for each joint,
the old value, new value and change in `id`, `homing_offset`, `range_min`,
`range_max` and `drive_mode`, plus joints present in only one. `format_diff`
turns the result into a readable table. Tested on the follower's real
calibration and a slightly changed copy. No command-line tool yet; the issue
did not ask for one.

## 2026-10-22 · LeRobot commands are built from the machine config

`hw_setup.lerobot_argv` builds the `lerobot-setup-motors`,
`lerobot-calibrate`, `lerobot-teleoperate` and `lerobot-record` commands
from `configs/local.yaml`: the follower's port, id and cameras go to
`--robot.*`, the leader's to `--teleop.*`, and both read their calibration
from `hardware/calibration/<role>/`. The tests feed every command to
LeRobot 0.6.1's own argument parser, so a wrong flag name fails them.
Nothing was run on hardware.

## 2026-10-22 · Every source module has tests, 100% covered

Coverage rose from 93% to 100% (line and branch) across `so101` and
`hw-setup`; run it with `uv run pytest --cov`. The calibration checks now
have edge tests: gripper width 300 and 2500 pass, 250 and 3000 fail, and a
range of exactly 200 passes. A test also checks the installed LeRobot is
0.6.1. Nothing was run on hardware.

## 2026-10-22 · First arm calibrations are committed, and checked in CI

The owner's initial calibrations of the leader and follower arms are now in
`hardware/calibration/{leader,follower}/main.json`. A new test loads every
JSON under `hardware/calibration/` and runs the sanity checks, one test per
file, so a bad calibration commit turns CI red and names the file. Both files
pass. Nothing was run on hardware in this task.

## 2026-10-22 · Repo checked against the org standard

The repo was checked row by row against the org's repo standard. The task
issue template now uses the same headings as the board's issues and points at
the project board, and local Claude session files no longer show up as
untracked. The README status is refreshed.

## 2026-10-22 · Type stubs no longer installed with so101

`types-pyyaml` moved from `so101`'s runtime dependencies to the workspace dev
group, so installing `so101` pulls in only `pyyaml`. `uv run ty check` still
passes.

## 2026-10-22 · A bad calibration now names the joint

`so101.check_calibration` checks a calibration for inverted ranges, ranges
too narrow to be real, a gripper span outside what the gripper can do, and
motor ids that do not match the joint order (1 to 6). Every failure is listed
with the joint and the check that caught it. Nothing was run on hardware.

## 2026-10-22 · LeRobot installed in the workspace

The new `hw-setup` project pins `lerobot[feetech]==0.6.1`, so LeRobot's arm
tools now run from the workspace. `lerobot-calibrate --help` works. No
hardware has been connected yet.

## 2026-10-22 · Machine config is checked on load

`so101` can now read `configs/local.yaml` and check it: each arm needs an id
and a serial port that looks like one, and each camera needs an index, width,
height and fps, with no two cameras sharing an index. A wrong file gives an
error that names the key, such as `cameras.front.fps: missing`.
`configs/example.yaml` passes. Nothing opens a port or a camera.

## 2026-10-22 · Repo scaffolded for the SO-101 arm

There is now one place for everything about the SO-101 arms: a uv workspace
with a shared `so101` package, a copyable project template, and folders for
calibration files, URDF, CAD and the bill of materials. The shared package
can already read and check a LeRobot calibration file, so a bad or partial
calibration is caught before it reaches a servo. No hardware has been
connected yet.
