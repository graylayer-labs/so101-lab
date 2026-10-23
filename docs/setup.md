# SO-101 runbook

From an unopened box to the first recorded dataset, one script per step.
Each step below says what its script checks before it asks LeRobot to touch
a servo, the exact command, what the dry run prints, and what to do when it
fails.

**None of the `so101-*` scripts has run on the arms yet.** Every output block
is a `--dry-run` (or an error case) run on a laptop with no arm attached. The
arms already have a first calibration (#39), made outside these scripts. See
[What has not been tested on hardware](#what-has-not-been-tested-on-hardware).

Outputs are shown with `<root>` for the workspace folder and `<home>` for the
home folder. Run commands from anywhere inside the workspace, with `uv run`.
Backup file names carry a UTC time stamp, so yours will differ.

## Before you start

1. **Parts.** Check what you have against [`hardware/bom.md`](../hardware/bom.md),
   row by row. Several rows are marked "Confirm (#29)": read the gear code
   (C001, C044, C046) and the voltage on each servo and each supply.
2. **Power supplies. The wrong voltage can burn out servos.**
   - The leader is always 5 V.
   - The follower is 5 V with 7.4 V servos, or 12 V (5 A or more) with 12 V
     servos. Read the label on the servos, then the label on the supply.
   - A 5 V and a 12 V supply look alike. Label each supply, and never plug the
     12 V one into the leader's board. Why, in full:
     [`hardware/bom.md`](../hardware/bom.md#servo-voltage-and-power-supply).
3. **Waveshare boards.** Both jumpers go on the `B` channel (USB), as the
   upstream guide says.
4. **macOS camera permission.** The first time a program opens a camera,
   macOS asks. Allow it for the terminal app you run these commands from
   (System Settings > Privacy & Security > Camera), then restart the terminal.
   If you refused once, the camera stays closed until you switch it on there.
   Only `so101-doctor --open-cameras`, `so101-teleop` and `so101-record` open
   cameras.
5. **Port names.** On macOS each USB serial port has two names,
   `/dev/cu.usbmodem*` and `/dev/tty.usbmodem*`. LeRobot accepts both. This
   workspace writes and prefers the `cu.*` name, which is what pyserial
   lists. See [Troubleshooting](#troubleshooting).

6. **Arms already assembled and calibrated?** The repo ships a first
   calibration of both arms (#39). If your arms are in that state, skip Steps
   2 and 3: do Install, Step 1 if `configs/local.yaml` does not exist yet,
   then Step 5 (the doctor) and Step 6 (teleop). Use `so101-calibrate` (Step 4)
   only after you reassemble an arm or replace a servo.

## Install

```bash
git lfs install                      # once per machine, before adding CAD files
uv sync --dev --all-packages         # installs the workspace, LeRobot 0.6.1 pinned
uv run so101-doctor                  # first look at the setup; reports only
```

`so101-doctor` opens no serial port, runs no LeRobot command and writes
nothing. Before you have a `configs/local.yaml` it fails on the config and
skips the rest. That is the expected first result. Output from a machine
with no `local.yaml`:

```text
PASS  python: 3.12.12
PASS  lerobot: 0.6.1 (pinned)
PASS  workspace: <root>
FAIL  config: machine config not found: <root>/configs/local.yaml. Run so101-find-ports, or copy configs/example.yaml to configs/local.yaml and edit it.
        fix: so101-find-ports  (writes configs/local.yaml)
        fix: cp configs/example.yaml configs/local.yaml  and edit it
WARN  ports: skipped: no valid machine config
        fix: fix the workspace or config check above, then run so101-doctor again
WARN  calibration: skipped: no valid machine config
        fix: fix the workspace or config check above, then run so101-doctor again
WARN  cameras: skipped: no valid machine config
        fix: fix the workspace or config check above, then run so101-doctor again

1 failed: config
```

Exit code 1. Each check prints PASS, WARN or FAIL, and every WARN and FAIL
has a `fix:` line. If `python` or `lerobot` fails, run
`uv sync --dev --all-packages` again.

## Step 1. Find the serial ports

`so101-find-ports`. Each arm's controller board appears as a serial port. The
script finds which port belongs to which arm and writes both into
`configs/local.yaml`.

**Checks before anything moves:** nothing moves in this step. The script never
opens a port: it lists them with pyserial. It refuses to write a config that
fails `so101.machine_config`.

```bash
uv run so101-find-ports --dry-run
```

With no `configs/local.yaml` yet, the dry run says it would create one from
the example:

```text
Dry run: nothing is read, listed, opened or written.
Would do, for the leader arm and then the follower arm:
  1. list ports with serial.tools.list_ports.comports() (opens none)
  2. ask you to unplug that arm's USB cable, then list again
  3. ask you to plug it back in and check the port returns
  4. the one port that disappeared is that arm's port
(lerobot-find-port is not run: it blocks on input() and writes nothing.)
Would write <root>/configs/local.yaml (create it from <root>/configs/example.yaml), setting:
  arms.leader.port = <port found for the leader arm>
  arms.follower.port = <port found for the follower arm>
The result is checked with so101.machine_config before it is written.
```

Then, with both controller boards plugged in by USB and their supplies connected (on a new kit, before assembly, that is just the two boards):

```bash
uv run so101-find-ports
```

It asks you to unplug the leader's USB cable and press Enter, then to plug it
back in, then the same for the follower. The port that vanished is that
arm's. Afterwards open `configs/local.yaml` and check the two ports differ.

**If it fails** (message on stderr, exit 1):

| Message | What to do |
|---|---|
| `no port disappeared; is it plugged in?` | The cable you pulled was not the arm's, or the arm was not connected. Plug both in and run again. |
| `more than one port disappeared` | Something else was unplugged at the same time. Unplug only the named arm. |
| `did not come back after replug` | Plug the cable into the same USB socket as before. The port name depends on the socket. |
| `no configs/example.yaml found above the current directory` | Run from inside the workspace. |

Cameras are not found by this step. Edit the `cameras:` block of
`configs/local.yaml` by hand (indices 0 and 1 in the example). Step 5 lists
the cameras the OS knows, and `--open-cameras` proves each index opens.

## Step 2. Set the motor IDs

`so101-setup-motors`, leader first, then follower. Every new servo has the
same ID. This step gives each one its own (gripper 6 down to shoulder pan 1)
and the right baud rate, written once to the servo's memory.

**Checks before anything moves:** `configs/local.yaml` exists and is valid (it
never falls back to the example). Then it prints the wiring order, the gear
ratio per joint and the power warning, and asks you to type `y`. Anything
else exits 1 and runs nothing. It does not check that the port exists or that
the supply has the right voltage: that is on you (see Before you start).

```bash
uv run so101-setup-motors --role leader --dry-run
```

```text
Motor setup for the leader arm.

Wiring order, gripper first. Connect the controller board to ONE motor
at a time; LeRobot asks before each one:
  motor id 6: gripper
  motor id 5: wrist_roll
  motor id 4: wrist_flex
  motor id 3: elbow_flex
  motor id 2: shoulder_lift
  motor id 1: shoulder_pan

Gear ratio per joint (leader):
  1 shoulder_pan: 1/191
  2 shoulder_lift: 1/345
  3 elbow_flex: 1/191
  4 wrist_flex: 1/147
  5 wrist_roll: 1/147
  6 gripper: 1/147

Power: the leader always uses 5 V.

Command: lerobot-setup-motors --teleop.type=so101_leader --teleop.port=/dev/cu.usbmodem0000000001 --teleop.id=main --teleop.calibration_dir=<root>/hardware/calibration/leader

Dry run: nothing was asked or run.
```

```bash
uv run so101-setup-motors --role follower --dry-run
```

```text
Motor setup for the follower arm.

Wiring order, gripper first. Connect the controller board to ONE motor
at a time; LeRobot asks before each one:
  motor id 6: gripper
  motor id 5: wrist_roll
  motor id 4: wrist_flex
  motor id 3: elbow_flex
  motor id 2: shoulder_lift
  motor id 1: shoulder_pan

Gear ratio per joint (follower):
  1 shoulder_pan: 1/345
  2 shoulder_lift: 1/345
  3 elbow_flex: 1/345
  4 wrist_flex: 1/345
  5 wrist_roll: 1/345
  6 gripper: 1/345

Power: the follower uses a 5 V supply, or 12 V if it has 12 V servos. Check the voltage printed on the supply and on the servos.

Command: lerobot-setup-motors --robot.type=so101_follower --robot.port=/dev/cu.usbmodem0000000002 --robot.id=main --robot.calibration_dir=<root>/hardware/calibration/follower

Dry run: nothing was asked or run.
```

Gear table, from the [LeRobot guide](https://huggingface.co/docs/lerobot/so101).
The servo codes come from [`hardware/bom.md`](../hardware/bom.md). When
LeRobot asks for a joint on the leader, plug in the servo with that row's
code: for 'gripper' a C046, for 'wrist_roll' a C046, for 'wrist_flex' a C046,
for 'elbow_flex' a C044, for 'shoulder_lift' a C001, for 'shoulder_pan' a
C044. Read the C0xx label on each servo before you plug it in.

| ID | Joint | Leader gear (servo code) | Follower gear |
|---|---|---|---|
| 1 | shoulder_pan | 1/191 (C044) | 1/345 |
| 2 | shoulder_lift | 1/345 (C001) | 1/345 |
| 3 | elbow_flex | 1/191 (C044) | 1/345 |
| 4 | wrist_flex | 1/147 (C046) | 1/345 |
| 5 | wrist_roll | 1/147 (C046) | 1/345 |
| 6 | gripper | 1/147 (C046) | 1/345 |

Run it for real, once per arm, with that arm's controller board powered and
connected by USB:

```bash
uv run so101-setup-motors --role leader
uv run so101-setup-motors --role follower
```

LeRobot then asks "Connect the controller board to the 'gripper' motor only
and press enter", and so on up the arm. Plug in one servo, press Enter, move
the cable to the next. Check the power cable at every step: it can slip while
you handle the board. When the script ends, daisy-chain the servos with the
3-pin cables and connect the first one (shoulder pan, ID 1) to the board.

**If it fails:** LeRobot reports an error at the first motor when something is
loose. Check, in order: the power supply, the USB cable to the board, the
3-pin cable to the motor, and the two jumpers on the `B` channel. A
`so101-setup-motors: machine config not found` message means there is no
`configs/local.yaml`: run Step 1.

## Step 3. Assemble both arms

No script. Follow the [LeRobot SO-101 guide](https://huggingface.co/docs/lerobot/so101#step-by-step-assembly-instructions),
joint 1 to the gripper, with the leader's handle and trigger on the leader.
Our advice, not from the upstream guide: route cables so every joint can
reach its full range, and clamp both bases to the table.

The guide advises installing one 3-pin cable in each servo as you place it.
Do this after Step 2, so every servo already has its ID.

Our advice, not from the upstream guide: treat reassembling an arm or
swapping a servo as invalidating its calibration, and run Step 4 for that arm
again.

## Step 4. Calibrate both arms

`so101-calibrate --role follower` and `--role leader`. Calibration makes the
same physical pose read as the same numbers on both arms, which is what lets
the follower copy the leader. The result lands in
`hardware/calibration/<role>/<id>.json`, with `<id>` from `configs/local.yaml`.

**Checks before anything moves:**

- `configs/local.yaml` is valid.
- If a calibration file already exists, it must load and pass
  `so101.check_calibration`. If not, the script refuses (below) before
  LeRobot runs, because LeRobot itself could crash loading it.
- An existing file is copied to
  `hardware/calibration/<role>/backups/<id>.<UTC time>.json.bak` first.

Calibrate the follower first, as LeRobot's guide does. Output when a file
already exists (the repo ships the owner's first calibration, #39). Note that
the script's own last-but-one line, "anything other than 'c' keeps the
existing file", understates what LeRobot does: see the warning below.

```bash
uv run so101-calibrate --role follower --dry-run
```

```text
Calibration file: <root>/hardware/calibration/follower/main.json
Backup: <root>/hardware/calibration/follower/backups/main.20261022T205800Z.json.bak
Command: lerobot-calibrate --robot.type=so101_follower --robot.port=/dev/cu.usbmodem0000000002 --robot.id=main --robot.calibration_dir=<root>/hardware/calibration/follower
LeRobot will find the existing file and ask what to do: type 'c' and press ENTER to recalibrate; anything other than 'c' writes the stored calibration file to the motors.
Dry run: nothing was backed up, moved, run or written.
```

Then the leader:

```bash
uv run so101-calibrate --role leader --dry-run
```

```text
Calibration file: <root>/hardware/calibration/leader/main.json
Backup: <root>/hardware/calibration/leader/backups/main.20261022T205800Z.json.bak
Command: lerobot-calibrate --teleop.type=so101_leader --teleop.port=/dev/cu.usbmodem0000000001 --teleop.id=main --teleop.calibration_dir=<root>/hardware/calibration/leader
LeRobot will find the existing file and ask what to do: type 'c' and press ENTER to recalibrate; anything other than 'c' writes the stored calibration file to the motors.
Dry run: nothing was backed up, moved, run or written.
```

For an id with no file yet (here a config with `id: spare`), the plan reads:

```text
Calibration file: <root>/hardware/calibration/leader/spare.json
Backup: none, first calibration
Command: lerobot-calibrate --teleop.type=so101_leader --teleop.port=/dev/cu.usbmodem0000000001 --teleop.id=spare --teleop.calibration_dir=<root>/hardware/calibration/leader
No calibration file yet: LeRobot goes straight to calibration.
Dry run: nothing was backed up, moved, run or written.
```

Run it for real, one arm at a time:

```bash
uv run so101-calibrate --role follower
uv run so101-calibrate --role leader
```

**Warning: ENTER at the first prompt writes the old file to the motors.**
When a calibration file exists, LeRobot first asks:

```text
Press ENTER to use provided calibration file associated with the id main, or type 'c' and press ENTER to run calibration:
```

Anything other than `c` does not just keep the file: LeRobot writes that
file's offsets and limits to the motors ("Writing calibration file associated
with the id main to the motors"). After a reassembly or a servo swap those
values are stale, and pressing ENTER by mistake pushes them onto the motors.
After a reassembly, type `c`. If you press ENTER instead, the script says
"Calibration file unchanged", removes the identical backup and exits 0.

After `c` (or with no file yet), LeRobot's prompts are, in order (quoted from
`so_follower.py` and `so_leader.py` in lerobot 0.6.1):

1. `Move <arm> to the middle of its range of motion and press ENTER....`
   Put every joint mid-range, then press ENTER.
2. `Move all joints except 'wrist_roll' sequentially through their entire
   ranges of motion.` then `Recording positions. Press ENTER to stop...`
   Move each joint, except the wrist roll, from one end to the other. Do not
   move `wrist_roll`: LeRobot fixes its range at 0 to 4095. When every joint
   has been through its full range, press ENTER to stop recording. Until you
   do, it keeps recording.

LeRobot then prints `Calibration saved to <path>`.

After a successful run the script loads the new file and prints a "Changes
per joint" table against the old file (first calibration: "no previous file,
so no backup and no diff"). It runs the sanity checks, prints
`Sanity checks passed: <path>` and, if there was one, the path of the
previous file.

**If it fails:**

| What you see | What it means | What to do |
|---|---|---|
| `the existing calibration file is unreadable` (exit 1, before LeRobot runs) | The file is not valid JSON or fails the checks, so LeRobot could crash on it. | Run the printed `mv` command to move it into `backups/`, or rerun with `--move-corrupt` to do the move and calibrate from scratch. |
| `failed the sanity checks` (exit 1, after the run) | The motors already hold the new values. Nothing is restored for you, because the checks may be wrong for your arm. | Read the message. Recalibrate, or restore the old file with the printed `cp` command. After a restore, LeRobot notices file and motors differ on the next connect and asks to write the file to the motors. |
| `lerobot-calibrate exited with code N`, or Ctrl-C (exit 130) | The file may be half-written. | Restore it with the printed `cp` command, then run again. |

Example of the refusal, from a deliberately broken file (dry run, exit 1):

```text
so101-calibrate: the existing calibration file is unreadable: Expecting value: line 2 column 1 (char 18)
LeRobot would crash loading it before it asks anything.
Move it aside, then run again:
  mkdir -p <root>/hardware/calibration/leader/backups
  mv <root>/hardware/calibration/leader/bad.json <root>/hardware/calibration/leader/backups/bad.20261022T205829Z.json.bak
or rerun with --move-corrupt to do that and calibrate.
```

Commit the new `hardware/calibration/<role>/<id>.json` files when you are
happy with them. The `backups/` folders are gitignored.

## Step 5. Run the doctor again

`so101-doctor`, now with both arms plugged in and powered, and
`configs/local.yaml` written.

**Checks before anything moves:** it is itself read-only. It checks the
Python and LeRobot versions, the config, that each configured port is in the
system's port list, that both calibration files pass the sanity checks, and
that the number of cameras the OS lists matches the number configured.

```bash
uv run so101-doctor                  # report only
uv run so101-doctor --open-cameras   # also open each configured camera
```

The first form opens no camera and no serial port. The second opens each
configured camera index and reads one frame, so it is where the macOS camera
prompt appears. On a failure it prints the permission hint.

Output on a laptop with no arms attached, against the example config
(`uv run so101-doctor --config configs/example.yaml`, exit 1).
Device names in the camera line are generic; yours will differ:

```text
PASS  python: 3.12.12
PASS  lerobot: 0.6.1 (pinned)
PASS  workspace: <root>
PASS  config: configs/example.yaml is valid
FAIL  ports: an arm port is not present
        leader: /dev/cu.usbmodem0000000001 not found
        follower: /dev/cu.usbmodem0000000002 not found
        listed by pyserial: /dev/cu.Bluetooth-Incoming-Port, /dev/cu.debug-console
        fix: plug in both arms and run: so101-find-ports  (or fix arms.<role>.port in configs/local.yaml)
PASS  calibration: leader and follower pass the checks
PASS  cameras: 2 listed, 2 configured (compares counts only)
        listed by the OS: MacBook Pro Camera, iPhone Camera (Continuity)
        this compares counts only: Linux may list two /dev/video* entries per camera, and phantom cameras (an iPhone Continuity camera) count too, so a PASS does not prove the right cameras are there; use --open-cameras
        not opened; add --open-cameras to open each configured index

1 failed: ports
```

With the arms attached the ports line should turn PASS, and the script ends
with `Nothing failed.` (exit 0). That all-PASS output has not been seen yet.

**If it fails:**

| Check | What to do |
|---|---|
| `ports` | Plug in both arms and run Step 1 again, or fix `arms.<role>.port` in `configs/local.yaml`. |
| `ports` WARN (`tty.* name`) | Optional. Change the config to the `cu.*` name shown. |
| `calibration` | Run the `so101-calibrate --role <role>` command in the `fix:` line (Step 4). |
| `cameras` WARN | Fewer cameras listed than configured: connect them, or edit `cameras:` in `configs/local.yaml`. |
| `cameras` FAIL with `--open-cameras` | Check the cable and that no other app holds the camera, then the macOS permission (Before you start). |

## Step 6. Teleoperate

`so101-teleop`. The leader drives the follower. This is the first step where
a servo moves under power.

**Checks before the follower moves:** both calibration files
(`hardware/calibration/<role>/<id>.json`) must exist, load, and pass
`so101.check_calibration`. If either does not, the script names the arm and
the problem on stderr and exits 1, also with `--dry-run`. It does not check
that the ports are present: run Step 5 first.

Our advice, not from the upstream guide: before the first run, hold the
leader near the pose the follower is in, clear the area around the follower,
and keep a hand on the power supply.

```bash
uv run so101-teleop --dry-run
```

```text
Calibration checked: leader and follower pass.
Command: lerobot-teleoperate --robot.type=so101_follower --robot.port=/dev/cu.usbmodem0000000002 --robot.id=main --robot.calibration_dir=<root>/hardware/calibration/follower '--robot.cameras={front: {type: opencv, index_or_path: 0, width: 640, height: 480, fps: 30}, wrist: {type: opencv, index_or_path: 1, width: 640, height: 480, fps: 30}}' --teleop.type=so101_leader --teleop.port=/dev/cu.usbmodem0000000001 --teleop.id=main --teleop.calibration_dir=<root>/hardware/calibration/leader
Dry run: nothing was run.
```

For real:

```bash
uv run so101-teleop --no-cameras     # first run: arms only
uv run so101-teleop                  # with the configured cameras
uv run so101-teleop --display        # also show the data live
```

Our advice, not from the upstream guide: try `--no-cameras` first, so a camera problem cannot hide an arm problem.

**If it fails:**

| What you see | What to do |
|---|---|
| `refusing to run: leader arm (id): calibration missing: <path>` | No file for that id. Run Step 4 for that arm, or fix `arms.<role>.id` in `configs/local.yaml`. |
| `refusing to run: ... calibration is not valid JSON`, or a sanity-check message | Run Step 4 for that arm. |
| `machine config not found` | No `configs/local.yaml`. Run Step 1. |
| LeRobot cannot open a port, or the follower does not move | Run `so101-doctor` (Step 5), then check the supply and cables. |

Example of the calibration gate (a config with `id: spare`, no such files,
exit 1):

```text
so101-teleop: refusing to run: leader arm (spare): calibration missing: <root>/hardware/calibration/leader/spare.json
so101-teleop: refusing to run: follower arm (spare): calibration missing: <root>/hardware/calibration/follower/spare.json
```

## Step 7. Record the first dataset

`so101-record`. Teleoperation as in Step 6, with the cameras, saving each
episode to a LeRobot dataset on this machine.

**Checks before the follower moves:** the same calibration check as Step 6.
Then, for the dataset:

- `--task` must have text, `--repo-id` must be `USER/NAME`, and `--episodes`
  at least 1. Names starting with `eval_` are refused for new datasets.
- It never pushes to the Hub. `--dataset.push_to_hub=false` is always passed
  (LeRobot defaults to pushing) and there is no flag to change it.
- The dataset root is `--dataset-root`, or by default
  `$HF_LEROBOT_HOME/USER/NAME` (`~/.cache/huggingface/lerobot/USER/NAME`
  unless set). It is resolved, printed, and refused if it is inside the
  workspace. Datasets never belong in the repo.
- An existing root is refused unless you pass `--resume`. With `--resume`,
  `--episodes` counts the episodes to add, and the root must hold complete
  local metadata. Otherwise LeRobot would fetch `meta/` for that name from
  the Hub, possibly a stranger's dataset.

```bash
uv run so101-record --task "Pick up the red cube" --repo-id me/cube --episodes 10 --dry-run
```

```text
Calibration checked: leader and follower pass.
Dataset: me/cube (new dataset)
Dataset root: <home>/.cache/huggingface/lerobot/me/cube
Task: Pick up the red cube
Episodes: 10
Push to Hub: no
Command: lerobot-record --robot.type=so101_follower --robot.port=/dev/cu.usbmodem0000000002 --robot.id=main --robot.calibration_dir=<root>/hardware/calibration/follower '--robot.cameras={front: {type: opencv, index_or_path: 0, width: 640, height: 480, fps: 30}, wrist: {type: opencv, index_or_path: 1, width: 640, height: 480, fps: 30}}' --teleop.type=so101_leader --teleop.port=/dev/cu.usbmodem0000000001 --teleop.id=main --teleop.calibration_dir=<root>/hardware/calibration/leader --dataset.repo_id=me/cube '--dataset.single_task=Pick up the red cube' --dataset.num_episodes=10 --dataset.root=<home>/.cache/huggingface/lerobot/me/cube --dataset.push_to_hub=false --dataset.no_stamp=true
Dry run: nothing was run.
```

For real, then to add more episodes after an interruption:

```bash
uv run so101-record --task "Pick up the red cube" --repo-id me/cube --episodes 10
uv run so101-record --task "Pick up the red cube" --repo-id me/cube --episodes 5 --resume
```

Optional: `--dataset-root PATH` (outside the repo), `--episode-time-s`,
`--reset-time-s` and `--fps` (LeRobot's defaults: 60 s, 60 s, 30 fps),
`--no-cameras`, `--display`.

**If it fails:**

| What you see | What to do |
|---|---|
| `holds an incomplete dataset (missing: meta/info.json)` and a `mv` command | A crash left a half-written folder. Run the printed `mv` to set it aside, then record again. Nothing is deleted. |
| The root exists and is complete, but you did not pass `--resume` | Pick a new `--repo-id`, or add `--resume` to add episodes. |
| `refusing to run: ... calibration ...` | As Step 6. |

Example of the incomplete-dataset refusal (an empty folder given as
`--dataset-root`, dry run, exit 1):

```text
so101-record: refusing to run: <scratch>/cubeexists holds an incomplete dataset (missing: meta/info.json). LeRobot can neither create a dataset there nor resume it without fetching metadata from the Hub. Set it aside and start again:
  mv <scratch>/cubeexists <scratch>/cubeexists.broken-20261022-215813
```

## Quick reference

The order, on a fresh machine with new arms:

```bash
git lfs install
uv sync --dev --all-packages
uv run so101-doctor                                   # expect a config FAIL
uv run so101-find-ports                               # writes configs/local.yaml
uv run so101-setup-motors --role leader               # one servo at a time
uv run so101-setup-motors --role follower
# assemble both arms (upstream guide)
uv run so101-calibrate --role follower                # type c if a file exists
uv run so101-calibrate --role leader
uv run so101-doctor --open-cameras                    # everything PASS
uv run so101-teleop --no-cameras                      # then without the flag
uv run so101-record --task "..." --repo-id USER/NAME --episodes 10
uv run so101-record --task "..." --repo-id USER/NAME --episodes 5 --resume
```

Add `--dry-run` to any `so101-*` command except `so101-doctor` to see the
plan without running it. The doctor has no `--dry-run`: it is read-only
already.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Port not found, with a `/dev/tty.usbmodem...` or `/dev/cu.usbmodem...` name | macOS gives each port two names. pyserial lists only the `cu.*` one. | Use the `cu.*` name in `configs/local.yaml` (what `so101-find-ports` writes). LeRobot accepts both. `so101-doctor` matches a `tty.*` name to its `cu.*` twin and warns. |
| Port name changed after replugging | The name depends on the USB socket. | Plug the arm back into the same socket, or run `so101-find-ports` again. |
| `so101-teleop` or `so101-record`: `refusing to run: ... calibration missing` | No `hardware/calibration/<role>/<id>.json` for the id in the config. | `so101-calibrate --role <role>`, or correct the id. |
| `so101-calibrate`: `existing calibration file is unreadable` | The file is not valid JSON or fails the checks. | Run the printed `mv`, or use `--move-corrupt`. |
| `so101-calibrate`: `failed the sanity checks` | The new file looks wrong. Nothing was restored. | Recalibrate, or restore with the printed `cp` command. |
| `so101-record`: `incomplete dataset` | Folder exists without full metadata, for example after a crash. | Run the printed `mv`, then record again. |
| `machine config not found: .../configs/local.yaml` | `local.yaml` is gitignored and not created yet. | `so101-find-ports`, or `cp configs/example.yaml configs/local.yaml` and edit. |
| `so101-doctor` cameras FAIL on macOS | Camera permission. | System Settings > Privacy & Security > Camera, switch on your terminal, restart it. |
| Motor or calibration errors after changing a servo | The servo's ID or calibration no longer matches. | Step 2 for that arm, then Step 4. |

## What has not been tested on hardware

None of the `so101-*` scripts has run on the arms. Every script is tested
with fakes, and every output above is a dry run or an error case with no arm
attached. The arms themselves were assembled, given IDs and calibrated
before these scripts existed (#39), outside them.

| Step | Tested | Not yet seen |
|---|---|---|
| 1. `so101-find-ports` | Unplug and replug logic with fake port lists | Real ports on the Mac; the `cu.*` names it writes; LeRobot accepting both `tty.*` and `cu.*` names |
| 2. `so101-setup-motors` | Command line parsed by LeRobot's own config classes | A real run: the per-motor prompts and the IDs written |
| 3. Assembly | - | Not covered by any script; the arms were built before this runbook |
| 4. `so101-calibrate` | Backup, diff, checks and failure paths with a fake LeRobot | A real run and the ENTER and `c` prompts; a real `--move-corrupt`; the Ctrl-C and half-written-file restore |
| 5. `so101-doctor` | Checks with fakes; ran on a laptop with no arm | An all-PASS run; `--open-cameras` on the real cameras; the macOS camera permission prompt |
| 6. `so101-teleop` | Gate and command line | The follower tracking the leader; `--display` |
| 7. `so101-record` | Gate, dataset checks and command line, parsed by LeRobot's `RecordConfig` | A real episode written, and `--resume` on a real dataset |

The calibration files in `hardware/calibration/` are the owner's first
calibrations from 2026-10-22 (#39), made outside the scripts. They pass the
checks.

## Progress checklist

Tick as you go and note anything that differed from the upstream guide.
Issue numbers are the owner's steps on the board.

- [ ] Every row of [`hardware/bom.md`](../hardware/bom.md) filled in and received; each servo's voltage checked against its supply (#29).
- [ ] Printed parts for both arms (#29).
- [ ] `uv sync --dev --all-packages` and `git lfs install` done.
- [ ] Ports found; `configs/local.yaml` written.
- [ ] Servo IDs 1 to 6 set on the leader and on the follower (#30).
- [ ] Both arms assembled; cables routed so every joint has its full range (#30).
- [ ] Follower calibrated; file in `hardware/calibration/follower/` (#31).
- [ ] Leader calibrated; file in `hardware/calibration/leader/` (#31).
- [ ] `so101-doctor --open-cameras` all PASS.
- [ ] Teleoperation: the follower tracks the leader (#32).
- [ ] First dataset recorded locally (#33).
