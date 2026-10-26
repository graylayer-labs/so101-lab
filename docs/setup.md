# SO-101 runbook

From an unopened box to the first recorded dataset, one script per step.
Each step below says what its script checks before it asks LeRobot to touch
a servo, the exact command, what the dry run prints, and what to do when it
fails.

**From 2026-10-23 to 2026-10-26 Steps 1 (by hand, not the script), 4, 5, 6
and 7 ran on the real arms** (notes below each step). Steps 5, 6 and 7 show
a real output block; the others show `--dry-run`s or error cases from a
laptop with no arm attached, and Step 4's real run was not saved. See
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
   OpenCV only checks the permission and never asks for it, so with OpenCV
   alone no prompt appears and a `tccutil reset Camera` is not enough. What
   worked on 2026-10-23: reset, then ask through AVFoundation, in the
   terminal you run the scripts from, and click Allow:

   ```bash
   tccutil reset Camera "${__CFBundleIdentifier:?unset: name the app, e.g. com.apple.Terminal}"
   printf '%s\n' 'import AVFoundation' 'let s = DispatchSemaphore(value: 0)' \
     'AVCaptureDevice.requestAccess(for: .video) { ok in print("granted:", ok); s.signal() }' \
     '_ = s.wait(timeout: .now() + 60)' > /tmp/camauth.swift
   swift /tmp/camauth.swift
   ```
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

On the real arms (2026-10-23) the same unplug test was done by hand, because
the script waits for ENTER and a Claude session's shell cannot press it.
Run the script in your own terminal. Both boards enumerate on USB power
alone, so the supplies can stay off for this step.

**If it fails** (message on stderr, exit 1):

| Message | What to do |
|---|---|
| `no port disappeared; is it plugged in?` | The cable you pulled was not the arm's, or the arm was not connected. Plug both in and run again. |
| `more than one port disappeared` | Something else was unplugged at the same time. Unplug only the named arm. |
| `did not come back after replug` | Plug the cable into the same USB socket as before. The port name depends on the socket. |
| `no workspace root found` | The tool is not installed from a checkout of the workspace. Pass `--config` and `--example`. |

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
"Calibration file unchanged" (and that LeRobot wrote the stored file to the
motors), removes the identical backup and exits 0.

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

**Pose both arms the same for the middle pose.** Each joint's zero is the
pose you hold at the first ENTER, and LeRobot never sweeps `wrist_roll`, so
its zero is wherever the wrist was turned. If the leader's middle pose
differs from the follower's, the arms disagree by exactly that much. On
2026-10-23 the first calibrations had the wrist rolls 174° apart and the
elbows 13° apart, which is why teleop snapped. After calibrating both from
the same pose (upright, elbow about 90°, wrist straight, gripper closed),
every joint was within 3.7°, and still within 2.5° the next day.

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

With the arms attached the ports line turns PASS, and the script ends with
`Nothing failed.` (exit 0), as on 2026-10-24 with both arms and the wrist
camera. Real output, 2026-10-26, `--open-cameras` (port names replaced):

```text
PASS  python: 3.12.12
PASS  lerobot: 0.6.1 (pinned)
PASS  workspace: <root>
PASS  config: <root>/configs/local.yaml is valid
PASS  ports: both arm ports present
        leader: /dev/cu.usbmodem000000000N found
        follower: /dev/cu.usbmodem000000000N found
PASS  calibration: leader and follower pass the checks
PASS  cameras: 2 listed, 1 configured (compares counts only)
        listed by the OS: USB2.0_CAM1, MacBook Pro Camera
        wrist (index 0): opened, frame read

Nothing failed.
```

**A PASS does not prove it opened the right camera.** On macOS the OpenCV
indices follow plug order. With the wrist camera unplugged, the MacBook
camera took index 0 and `--open-cameras` still passed. Check the camera's
name is in the `listed by the OS` line, and look at a frame.

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

**Alignment check:** then it connects to both arms read-only and refuses
(exit 1, with a per-joint table) if any joint of the leader and follower
differs by more than `--align-max` (default 5 degrees, or 5 % of range for
the gripper). It sends no goal and does not change torque. `--dry-run` does
not connect. `--skip-align` skips it with a warning.

**Movement cap:** every command passes `--robot.max_relative_target`
(`--max-step`, default 5: at most 5 degrees per update for the body joints
and 5 % of range for the gripper). `--max-step none` removes it and prints a
warning. See the hw-setup README for why 5.

Our advice, not from the upstream guide: before the first run, hold the
leader near the pose the follower is in, clear the area around the follower,
and keep a hand on the power supply.

First pose the arms the same. With both arms powered and plugged in:

```bash
uv run so101-align --watch
```

Move the leader (and the follower by hand, if its torque is off, as it is
after a LeRobot command exits; this check never changes it) until every row
of the table says `ok`, then press Ctrl-C. The last reading is saved to
`outputs/hw/alignment-<UTC time>.json`. If one joint stays `OVER` although
the arms look the same (on 2026-10-22: elbow_flex 10-13°, wrist_roll about
98° until the wrist was twisted), the two calibrations disagree: recalibrate
that arm with Step 4 and check again.

```bash
uv run so101-teleop --dry-run
```

```text
Calibration checked: leader and follower pass.
Alignment check: would run (connect both arms read-only, refuse if any joint differs by more than 5.0); not run under --dry-run.
Movement cap: 5.0 per update (degrees for body joints, % of range for the gripper)
Command: lerobot-teleoperate --robot.type=so101_follower --robot.port=/dev/cu.usbmodem0000000002 --robot.id=main --robot.calibration_dir=<root>/hardware/calibration/follower '--robot.cameras={front: {type: opencv, index_or_path: 0, width: 640, height: 480, fps: 30}, wrist: {type: opencv, index_or_path: 1, width: 640, height: 480, fps: 30}}' --teleop.type=so101_leader --teleop.port=/dev/cu.usbmodem0000000001 --teleop.id=main --teleop.calibration_dir=<root>/hardware/calibration/leader --robot.max_relative_target=5.0
Dry run: nothing was run.
```

For real:

```bash
uv run so101-teleop --no-cameras     # first run: arms only
uv run so101-teleop                  # with the configured cameras
uv run so101-teleop --display        # also show the data live
```

Our advice, not from the upstream guide: try `--no-cameras` first, so a camera problem cannot hide an arm problem.

On the real arms (2026-10-23) the alignment check refused before the
recalibration and passed after it; teleop then ran with no snap.
`--display` opens a Rerun window; it needs LeRobot's `viz` extra, which
hw-setup installs. The wrist camera's picture was blurred until its lens was
twisted to focus at the gripper.

Real `so101-align` output, 2026-10-26, after moving the leader to match
(the first reading had shoulder_pan 9.5° and wrist_roll 6.8° OVER):

```text
joint             leader  follower      diff   limit  status
shoulder_pan       -2.0°      1.0°     -3.0°    5.0°  ok
shoulder_lift    -101.5°   -103.2°     +1.8°    5.0°  ok
elbow_flex         99.5°     97.0°     +2.5°    5.0°  ok
wrist_flex       -101.0°   -100.4°     -0.5°    5.0°  ok
wrist_roll         82.2°     82.2°     +0.1°    5.0°  ok
gripper             0.3%      0.5%     -0.2%    5.0%  ok
Saved: outputs/hw/alignment-20261026T142859Z.json
Aligned: every joint within 5.0.
```

**To stop teleop, rest the follower on the table first, then press Ctrl-C.**
LeRobot switches the follower's torque off when it disconnects, so it goes
limp at once and falls if it is held up.

**If it fails:**

| What you see | What to do |
|---|---|
| `refusing to run: leader arm (id): calibration missing: <path>` | No file for that id. Run Step 4 for that arm, or fix `arms.<role>.id` in `configs/local.yaml`. |
| `refusing to run: ... calibration is not valid JSON`, or a sanity-check message | Run Step 4 for that arm. |
| `ImportError: 'rerun-sdk' is required` with `--display` | Run `uv sync --dev --all-packages`; the `viz` extra is a dependency of hw-setup. |
| Camera picture blurred | Peel any film off the lens, then twist the lens barrel while watching `--display`. |
| `machine config not found` | No `configs/local.yaml`. Run Step 1. |
| LeRobot cannot open a port, or the follower does not move | Run `so101-doctor` (Step 5), then check the supply and cables. |
| `refusing to run: leader and follower disagree (<joints>)` and a table | Run `so101-align --watch` and pose the arms until every row is `ok`. If a joint stays `OVER` in the same pose, recalibrate that arm (Step 4). |
| `refusing to run: could not read the arms: ...` | A port or motor did not answer. Run `so101-doctor` (Step 5) and check power and cables. |
| A table line `the motors hold a different calibration from ...` | The motors and the file disagree. Recalibrate that arm (Step 4). |

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
Alignment check: would run (connect both arms read-only, refuse if any joint differs by more than 5.0); not run under --dry-run.
Dataset: me/cube (new dataset)
Dataset root: <home>/.cache/huggingface/lerobot/me/cube
Task: Pick up the red cube
Episodes: 10
Push to Hub: no
Movement cap: 5.0 per update (degrees for body joints, % of range for the gripper)
Command: lerobot-record --robot.type=so101_follower --robot.port=/dev/cu.usbmodem0000000002 --robot.id=main --robot.calibration_dir=<root>/hardware/calibration/follower '--robot.cameras={front: {type: opencv, index_or_path: 0, width: 640, height: 480, fps: 30}, wrist: {type: opencv, index_or_path: 1, width: 640, height: 480, fps: 30}}' --teleop.type=so101_leader --teleop.port=/dev/cu.usbmodem0000000001 --teleop.id=main --teleop.calibration_dir=<root>/hardware/calibration/leader --robot.max_relative_target=5.0 --dataset.repo_id=me/cube '--dataset.single_task=Pick up the red cube' --dataset.num_episodes=10 --dataset.root=<home>/.cache/huggingface/lerobot/me/cube --dataset.push_to_hub=false --dataset.no_stamp=true
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

**On the real arms (2026-10-26).** First dataset: 5 episodes of "Pick up the
block and place it in the plant pot", wrist camera only, 30 s episodes and
20 s resets. 4,500 frames, 18 MB, and it loads with `LeRobotDataset`. What
to expect while it runs:

- After the `Command:` line it prints nothing for about 25 to 40 s while
  LeRobot loads and connects. Wait: the Rerun viewer opens and the Mac says
  "Recording episode 0". A Ctrl-C in that gap stops it before anything is
  written.
- The keys (right arrow ends an episode early, left arrow re-records it,
  Esc stops) only work if the terminal app has Accessibility permission:
  System Settings > Privacy & Security > Accessibility. Without it, every
  episode runs the full `--episode-time-s`.
- After the last episode the follower holds its pose, still powered,
  while the dataset is written, then goes limp. That pause is not a stall.
- The arm puts the block in; you take it out by hand during the reset.

Real output, start and end (the `Command:` line and LeRobot's per-episode
log left out):

```text
Calibration checked: leader and follower pass.
joint             leader  follower      diff   limit  status
shoulder_pan        1.3°      1.5°     -0.2°    5.0°  ok
shoulder_lift    -101.5°   -101.8°     +0.3°    5.0°  ok
elbow_flex         99.5°     96.9°     +2.5°    5.0°  ok
wrist_flex       -101.0°   -100.3°     -0.7°    5.0°  ok
wrist_roll         82.8°     83.0°     -0.3°    5.0°  ok
gripper             0.5%      0.6%     -0.1%    5.0%  ok
Alignment checked: every joint within 5.0.
Dataset: graylayer/so101-first (new dataset)
Dataset root: <home>/.cache/huggingface/lerobot/graylayer/so101-first
Task: Pick up the block and place it in the plant pot
Episodes: 5
Push to Hub: no
Movement cap: 5.0 per update (degrees for body joints, % of range for the gripper)
...
INFO ... Stop recording
INFO ... OpenCVCamera(0) disconnected.
INFO ... main SOFollower disconnected.
INFO ... main SOLeader disconnected.
INFO ... Exiting
```

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

## Step 8. Evaluate a trained policy

`so101-eval` (in `projects/act-policy`). It runs a checkpoint on the
follower with `lerobot-rollout`, one episode per trial, and asks you to
score each trial. The leader is not used. Full rules: the
[act-policy README](../projects/act-policy/README.md#evaluate-a-policy).

**Checks before the follower moves**, also with `--dry-run`: the follower's
calibration; the checkpoint folder (`config.json`, `model.safetensors`,
`train_config.json` and the two `policy_*processor.json` files); the cameras in `configs/local.yaml` against the
policy and its training dataset (names, size, fps); the device; and the
dataset-root rules of Step 7. It never pushes to the Hub.

```bash
uv run so101-eval --policy <policy> --task "Pick the cube and place it in the bin" --episodes 10 --dry-run
```

```text
so101-eval: WARNING: running the policy on mps. A published SO-101 ACT eval measured about 15 Hz on an Apple M4 with mps and 40% success, against 30 Hz and 90% on CUDA for the same checkpoint. LeRobot logs 'Record loop is running slower' whenever a step misses the target fps. If the loop runs below about 25 Hz, write the rate down with the trials and rerun one diagnostic with --device cpu or without --display. The movement cap (--max-step) also costs rate: it adds a bus read of the follower's position on every step. It is a safety limit, so keep it, but say it was on when you compare rates.
Calibration checked: follower passes (the leader is not used).
Policy: <policy> (act, checkpoint last)
Trained on: local/pick_cube at <datasets>/pick_cube
Cameras checked: front 640x480, wrist 640x480 at 30 fps match
Device: mps
Teleop: none; after each trial LeRobot returns the follower to its start pose
Dataset: local/rollout_act_pick_cube_20261101_last (new dataset)
Dataset root: <home>/local/rollout_act_pick_cube_20261101_last
Task: Pick the cube and place it in the bin
Time limit: 30.0 s per trial
Trials: 10 (one lerobot-rollout each; trials after the first add --resume=true)
Push to Hub: no
Movement cap: 5.0 per update (degrees for body joints, % of range for the gripper)
Trial log: <root>/outputs/eval/act_pick_cube_20261101/last/trials.jsonl
Command: lerobot-rollout --strategy.type=episodic --policy.path=<policy> --policy.device=mps --device=mps --robot.type=so101_follower --robot.port=/dev/cu.usbmodem0000000002 --robot.id=main --robot.calibration_dir=<root>/hardware/calibration/follower '--robot.cameras={front: {type: opencv, index_or_path: 0, width: 640, height: 480, fps: 30}, wrist: {type: opencv, index_or_path: 1, width: 640, height: 480, fps: 30}}' --robot.max_relative_target=5.0 --dataset.repo_id=local/rollout_act_pick_cube_20261101_last '--dataset.single_task=Pick the cube and place it in the bin' --dataset.root=<home>/local/rollout_act_pick_cube_20261101_last --dataset.num_episodes=1 --dataset.fps=30 --dataset.push_to_hub=false --dataset.no_stamp=true --dataset.episode_time_s=30.0 --fps=30 --display_data=false
Start pose: not checked; each trial asks for y first.
Dry run: nothing was run.
```

(`<policy>` is `.../act_pick_cube_20261101/checkpoints/last/pretrained_model`,
a checkpoint made for the test without training; `<home>` is
`$HF_LEROBOT_HOME`.)

For real:

1. Put the follower at its rest pose, the pose the training episodes started
   from. LeRobot records the pose it connects in and drives the follower back
   to it after the episode.
2. Place the cube, then type `y` at the prompt.
3. During the episode: right arrow ends it early, left arrow re-records it,
   Escape stops (use it for safety; score the trial as a fail). Ctrl-C also
   stops it cleanly and leaves the trial unscored. Press it once only: the
   arm first holds still while LeRobot saves the episode's video, which can
   take a while, then returns to the start pose. A second Ctrl-C makes
   LeRobot exit at once, possibly mid-move. The stopped trial's episode is
   still saved; it is logged with `"interrupted": true` and no score.
   **At the end of every trial the follower loses torque and goes limp**
   (LeRobot disconnects with `disable_torque_on_disconnect=True`): support
   the arm or let it rest in a safe pose before the trial ends.
4. Score it at the prompts: `y`/`n` against #76's success definition, the
   furthest stage for a fail (`0 none`, `1 reach`, `2 grasp`, `3 lift`,
   `4 over the bin`, `5 released in the bin`), the start position and a
   note. Each trial is saved to `outputs/eval/<run>/<checkpoint>/trials.jsonl` at once,
   with the control rate measured from LeRobot's output (`Control rate:
   ... Hz` is printed; under 25 Hz there is a warning to note it with the
   result).

To add trials later, run the same command with `--resume`.

**If it fails:**

| What you see | What to do |
|---|---|
| `camera names differ` or `camera front: configs/local.yaml is 640x480; the policy was trained on ...` | Set `configs/local.yaml` back to the cameras the dataset was recorded with. Do not rename or resize a camera for a trained policy. |
| `training dataset metadata not found` | Pass `--train-dataset` with the dataset folder the policy was trained on. |
| `policy ... is missing model.safetensors` | Point `--policy` at a `checkpoints/<step>/pretrained_model` folder. |
| `device cuda is not available here` | Drop `--device` to pick one automatically. |

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
uv run so101-eval --policy <checkpoint>/pretrained_model --task "..." --episodes 10
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
| `camera access has been denied` and no prompt ever appears | OpenCV checks the permission but never asks for it. | The `tccutil reset` and `swift` commands in [Before you start](#before-you-start), step 4. |
| The camera shows the wrong picture | OpenCV indices on macOS follow plug order. | Plug the camera in, look at a frame from each index and set `index` in `configs/local.yaml`. |
| `so101-record` prints nothing after `Command:` | LeRobot is still loading (about 25 s on the first run). | Wait up to a minute for the viewer and "Recording episode 0". |
| Arrow keys do nothing during `so101-record` | The terminal app has no Accessibility permission. | System Settings > Privacy & Security > Accessibility, switch on your terminal, restart it. |
| Motor or calibration errors after changing a servo | The servo's ID or calibration no longer matches. | Step 2 for that arm, then Step 4. |

## What has not been tested on hardware

Every script is tested with fakes. Between 2026-10-23 and 2026-10-26 Steps 1
(by hand), 4, 5, 6 and 7 ran on the real arms. The arms were assembled and
given IDs before these scripts existed (#39), outside them.

| Step | Tested | Not yet seen |
|---|---|---|
| 1. `so101-find-ports` | Unplug and replug logic with fake port lists; the same test done by hand on the real arms | The script itself on the real arms; LeRobot accepting a `tty.*` name |
| 2. `so101-setup-motors` | Command line parsed by LeRobot's own config classes | A real run: the per-motor prompts and the IDs written |
| 3. Assembly | - | Not covered by any script; the arms were built before this runbook |
| 4. `so101-calibrate` | Backup, diff, checks and failure paths with a fake LeRobot; a real `c` run on both arms (2026-10-23) | A real `--move-corrupt`; the Ctrl-C and half-written-file restore |
| 5. `so101-doctor` | Checks with fakes; all PASS on the real arms with `--open-cameras` | That it opened the right camera (it cannot tell yet) |
| 6. `so101-teleop` | Gate and command line; on the real arms with and without the camera, and `--display` | - |
| 7. `so101-record` | Gate, dataset checks and command line, parsed by LeRobot's `RecordConfig`; 5 real episodes with the wrist camera (2026-10-26) | `--resume` on a real dataset; the episode keys (no Accessibility permission yet) |
| 8. `so101-eval` | Gates, trial log and command line, parsed by LeRobot's `RolloutConfig` with a checkpoint saved by LeRobot's own config savers | A real rollout; the return to the start pose; the control rate on mps (#81) |

The calibration files in `hardware/calibration/` were made with
`so101-calibrate` on 2026-10-23, from a matched pose. They replace the first
calibrations of 2026-10-22 (#39), which disagreed.

## Progress checklist

Tick as you go and note anything that differed from the upstream guide.
Issue numbers are the owner's steps on the board.

- [ ] Every row of [`hardware/bom.md`](../hardware/bom.md) filled in and received; each servo's voltage checked against its supply (#29).
- [ ] Printed parts for both arms (#29).
- [ ] `uv sync --dev --all-packages` and `git lfs install` done.
- [x] Ports found; `configs/local.yaml` written.
- [ ] Servo IDs 1 to 6 set on the leader and on the follower (#30).
- [ ] Both arms assembled; cables routed so every joint has its full range (#30).
- [x] Follower calibrated; file in `hardware/calibration/follower/` (#31).
- [x] Leader calibrated; file in `hardware/calibration/leader/` (#31).
- [x] `so101-doctor --open-cameras` all PASS.
- [x] Teleoperation: the follower tracks the leader (#32).
- [x] First dataset recorded locally (#33).
