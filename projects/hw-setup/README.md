# hw-setup

Gets the SO-101 arms ready for use: finds their serial ports, sets motor IDs
and calibrates them with LeRobot's tools, run from this workspace.

## Goal

LeRobot is installed in the workspace and the arm tools run from it.

## Expected results

`uv run lerobot-calibrate --help` exits 0. Success is exit code 0; failure is
any import or install error.

## Status (2026-10-22)

- Done: `lerobot[feetech]==0.6.1` pinned and installed; LeRobot commands
  built from the machine config (`hw_setup.lerobot_argv`).
- Done: `so101-setup-motors` (guided motor setup, `--dry-run`).
- Done: `so101-teleop` (calibration-gated teleoperation, `--dry-run`).
- Done: `so101-record` (local datasets only, resume, `--dry-run`);
  `lerobot[feetech,dataset]` installed.
- Done: `so101-find-ports` (tested with fakes; not yet run on hardware).
- Done: `so101-calibrate` (tested with fakes; not yet run on hardware).
- Done: `so101-doctor` (read-only preflight, tested with fakes).
- Doing: nothing.
- Next: set motor IDs (needs hardware).

## Find the ports

```bash
uv run so101-find-ports --dry-run   # print the plan; touches nothing
uv run so101-find-ports             # needs both arms plugged in
```

For the leader and then the follower arm it asks you to unplug the USB cable,
then plug it back in, and takes the port that disappeared. It lists ports with
pyserial, which does not open them. It then writes `arms.leader.port` and
`arms.follower.port` to `configs/local.yaml` (created from
`configs/example.yaml` if missing), keeps the other keys, and refuses to write
a file that fails `so101.machine_config`. Comments in an existing
`local.yaml` are not kept; its file mode is. With no `--config` it uses
`<workspace root>/configs/local.yaml`. The root is found by walking up from
the package file (`hw_setup.workspace`), so it works from any directory.
If an arm does not come back after the replug, plug it into the same USB
socket: the macOS port name depends on the socket.

This does not call `lerobot-find-port`: that tool blocks on `input()`,
globs `/dev/tty*` and writes nothing, so it cannot be tested or scripted.

## Calibrate an arm

```bash
uv run so101-calibrate --role follower --dry-run   # print the plan; touches nothing
uv run so101-calibrate --role follower             # needs the arm plugged in
```

It runs `lerobot-calibrate` for one arm (`--role leader` or `follower`) with
`calibration_dir` set to `hardware/calibration/<role>`, so the result lands in
`hardware/calibration/<role>/<id>.json`, with `<id>` from
`configs/local.yaml` (or `--config PATH`).

- Before the run, an existing file is copied to
  `hardware/calibration/<role>/backups/<id>.<UTC time>.json.bak`. LeRobot only
  reads `<id>.json`, and the `.bak` suffix keeps backups out of the CI check
  on every `*.json`. The `backups/` folders are gitignored.
- When the file exists, LeRobot asks first: type `c` and press ENTER to
  recalibrate. Anything other than `c` writes the stored file to the motors
  and leaves the file as it was; the script then says the file is unchanged and removes the identical backup.
- An existing file that cannot be loaded or fails the sanity checks is
  refused before LeRobot runs; the error says whether LeRobot itself would
  crash loading it. The error prints the `mv` command
  that moves it to the backup path; `--move-corrupt` does that move and
  calibrates from scratch.
- Ctrl-C during the run (exit 130) or a LeRobot error prints the backup path
  and the `cp` command to restore it, since the file may be half-written.
- After the run, the new file is loaded, checked with
  `so101.check_calibration`, and compared with the old one per joint.
- First calibration (no file yet): no backup and no diff, and it says so.
- A failed check exits 1 and prints where the backup is and the `cp` command
  to restore it. Nothing is restored automatically: the motors already hold
  the new values, and the checks may be wrong for your arm. After a restore,
  LeRobot notices the file and motors differ on the next connect and asks to
  write the file to the motors.

## Check the setup

```bash
uv run so101-doctor                     # report only; works with no arm attached
uv run so101-doctor --open-cameras      # also open each configured camera
uv run so101-doctor --config PATH       # default: configs/local.yaml
```

Each check prints PASS, WARN or FAIL on one line, and a `fix:` line for every
WARN and FAIL. Exit 0 when nothing FAILs, otherwise 1. It opens no serial
port, runs no LeRobot command and writes nothing.

- Python >= 3.12, and the installed `lerobot` equals the pin (0.6.1), read
  with `importlib.metadata`.
- Workspace root found; the machine config exists and validates.
- Each `arms.<role>.port` is in the pyserial listing. pyserial lists only
  `/dev/cu.*` names on macOS, so a configured `/dev/tty.*` name is matched by
  its `cu.*` twin and gets a WARN to switch to the `cu.*` name (LeRobot accepts
  both).
- Calibrations pass `calibration_problems`; each problem is printed with its
  `so101-calibrate --role <role>` command.
- Cameras are listed without being opened (macOS `system_profiler`, Linux
  `/dev/video*`). LeRobot's `lerobot-find-cameras` opens every index with
  `cv2.VideoCapture`, so it is not used. With `--open-cameras` each configured
  index is opened and one frame is read; on macOS a failure prints the camera
  permission hint (System Settings > Privacy & Security > Camera). The default
  check compares counts only: Linux may list two `/dev/video*` entries per
  camera, and phantom cameras such as an iPhone Continuity camera count, so a
  PASS there does not prove the right cameras are present.

Example output from one machine (a MacBook with no arms attached, run with
`--config configs/example.yaml`; `<root>` stands for the workspace path). Your
lines will differ:

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

## LeRobot commands

`hw_setup.lerobot_argv` turns the machine config into LeRobot command lines.
Each builder returns a `list[str]` and runs nothing; `format_command` joins
one into a line to paste into a shell.

```python
from pathlib import Path

from hw_setup.lerobot_argv import calibrate_argv, format_command
from so101 import ArmRole, load_machine_config

repo = Path(".")
config = load_machine_config(repo / "configs" / "local.yaml")
print(format_command(calibrate_argv(config, ArmRole.LEADER, repo.resolve())))
# lerobot-calibrate --teleop.type=so101_leader --teleop.port=/dev/cu.usbmodem...
#   --teleop.id=main --teleop.calibration_dir=<repo>/hardware/calibration/leader
```

- `setup_motors_argv` and `calibrate_argv` take one arm (`ArmRole`).
- `teleoperate_argv` and `record_argv` use both arms and the cameras.
  `record_argv` takes the dataset `repo_id`, `single_task` and
  `num_episodes`, plus optional `dataset_root`, `episode_time_s`,
  `reset_time_s`, `fps`, `push_to_hub`, `no_stamp`, `cameras`,
  `display_data` and `resume`. Options left out use LeRobot's defaults, and
  LeRobot pushes to the Hub by default.
- The follower goes to `--robot.*`, the leader to `--teleop.*`.
  `calibration_dir` points at `hardware/calibration/<role>`, where LeRobot
  reads `<id>.json`.
- The flag names were checked against lerobot 0.6.1; the module docstring
  lists the source file and line of each.
- The tests parse every argv with LeRobot's own config classes, including
  `RecordConfig` (`lerobot-record` needs the `dataset` extra, now installed).

## Set the motor IDs

```bash
uv run so101-setup-motors --role leader --dry-run   # show everything, run nothing
uv run so101-setup-motors --role follower           # asks, then runs LeRobot
```

Before it runs anything it prints the wiring order (gripper first, one motor
on the controller board at a time), the gear ratio of each joint (leader
1/191 on joints 1 and 3, 1/345 on 2, 1/147 on 4 to 6; follower 1/345 on all)
and the power warning (the leader always uses 5 V; the follower uses 5 V, or
12 V with 12 V servos). Then it asks `y` to continue; anything else exits 1.
`--dry-run` also prints the exact command and exits 0 without asking.
`--config PATH` overrides the default `configs/local.yaml` in the workspace
root, which is found from the package, not the current directory. If that
file is missing the command fails with a hint; it never uses the example.
## Teleoperate

```bash
uv run so101-teleop --dry-run            # check calibrations, print the command
uv run so101-teleop --no-cameras         # leader drives follower, no cameras
uv run so101-teleop --display            # also show the data live
```

First it checks `hardware/calibration/<role>/<id>.json` for both arms (the id
is from the machine config) with `so101.load_calibration` and
`so101.check_calibration`. If either file is missing or fails, it prints the
arm and the problem to stderr and exits 1; this also applies to `--dry-run`.
Then it runs `lerobot-teleoperate` (or, with `--dry-run`, prints the exact
command and exits 0). Cameras are on by default; `--config PATH` overrides
`configs/local.yaml` in the workspace root, which has no fallback to the
example.

## Record a dataset

```bash
uv run so101-record --task "Pick up the red cube" --repo-id me/cube \
    --episodes 10 --dry-run              # check everything, print the command
uv run so101-record --task "Pick up the red cube" --repo-id me/cube \
    --episodes 10                        # record 10 episodes
uv run so101-record --task "Pick up the red cube" --repo-id me/cube \
    --episodes 5 --resume                # add 5 more after an interruption
```

The leader drives the follower as in `so101-teleop`, and the same calibration
check runs first, also with `--dry-run`. Then:

- The dataset stays local: `--dataset.push_to_hub=false` is always passed
  (LeRobot defaults to pushing) and there is no flag to change it.
- `--task` must have text; empty or whitespace-only is refused.
  `--repo-id` must be `USER/NAME`; `--episodes` must be 1 or more.
- The dataset is written to `--dataset-root`, or by default to LeRobot's own
  `$HF_LEROBOT_HOME/USER/NAME` (`~/.cache/huggingface/lerobot/USER/NAME`
  unless set). The path is resolved and printed, and refused if it is inside
  the workspace.
- `--dataset.no_stamp=true` is always passed, so LeRobot keeps the name as
  given instead of adding a date-time tag; the printed root is where the data
  goes.
- An existing dataset root is refused unless you pass `--resume`: LeRobot
  cannot create a dataset in an existing folder. With `--resume`,
  `--episodes` counts the episodes to add.
- `--resume` needs the full local metadata: `meta/info.json`, plus
  `meta/tasks.parquet` and `meta/episodes/*/*.parquet` once info counts
  tasks and episodes. If any of these is missing, LeRobot would download
  `meta/` for that name from the Hub, possibly a stranger's dataset, so it is
  refused.
- A root with incomplete metadata (for example after a crash) is reported as
  an incomplete dataset, with an `mv <root> <root>.broken-<time>` command to
  set it aside. Nothing is deleted.
- New dataset names may not start with `eval_` (LeRobot keeps them for policy
  evaluation). Resuming an existing `eval_` dataset is allowed, as in LeRobot.
- `--episode-time-s`, `--reset-time-s` and `--fps` are passed only when
  given (LeRobot's defaults: 60 s, 60 s, 30 fps). `--no-cameras`,
  `--display` and `--config PATH` work as in `so101-teleop`.

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
