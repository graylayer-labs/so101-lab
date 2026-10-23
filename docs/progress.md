# Progress

Newest first. One entry per merged task or chunk.

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
