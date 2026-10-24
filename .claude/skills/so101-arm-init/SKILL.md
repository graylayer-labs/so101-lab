---
name: so101-arm-init
description: Bring the SO-101 leader and follower arms up on this laptop with the owner at the arms. Quick path (about 2 minutes) when they are already calibrated; full path for a first setup, a reassembly or a servo swap. Use when the owner says the arms are plugged in, or asks to initialise, start up or check the arms.
---

# so101-arm-init

## Outcome

The arms are ready to teleoperate or record: both ports match
`configs/local.yaml`, `so101-doctor --open-cameras` passes, the wrist camera
picture is the right camera and in focus, and `so101-align` says every joint
is within 5 degrees. The owner gets one message saying so, with the next
command to run.

Full runbook with every message and failure: `docs/setup.md`.

## Who does what

- **Agent runs, without asking:** `ls /dev/cu.usbmodem*`,
  `uv run so101-doctor --open-cameras`, the camera snapshot below,
  `uv run so101-align`, and any `--dry-run`. None of these moves a servo or
  changes torque.
- **Owner runs, in their own terminal pane:** anything that waits for keys
  or moves the follower: `so101-calibrate`, `so101-teleop`, `so101-record`,
  `so101-align --watch`. The agent's shell cannot answer prompts or send
  Ctrl-C. Give the exact command and wait for the pasted output.
- **The follower moves only with the owner at the arms.** Say what will move
  before each such command.
- **Power:** supplies off until step 3. Ports, doctor and camera need USB
  only. Both supplies are 5 V (`hardware/bom.md`); a 12 V supply never goes
  on the leader. Power off whenever something buzzes, stalls or gets hot.

## Quick path (arms already calibrated)

Keep the owner's turns to: plug in, power on, pose. Report once at the end
unless a step fails. Use short questions they can answer in one word.

1. **USB check (agent).** Run, in one call:

   ```bash
   ls /dev/cu.usbmodem*
   system_profiler SPCameraDataType | grep -E '^ {4}\S.*:$'
   uv run so101-doctor --open-cameras
   ```

   The camera list must include the wrist camera, `USB2.0_CAM1`. If it is
   missing, the doctor can still pass by opening another camera at the same
   index (2026-10-24: index 0 was the MacBook camera), so ask the owner to
   plug the wrist camera's USB cable in and rerun. Every doctor line PASS,
   or WARN only: go on. On a FAIL go to the matching fix
   below, then rerun this step.
2. **Camera look (agent).** Save one frame of each configured camera to the
   scratchpad and Read the image. Check it is the follower's wrist camera
   (the gripper jaws are in view) and not blurred. Run from the repo root:

   ```bash
   uv run --package hw-setup python - <scratchpad dir> <<'EOF'
   import sys, time, cv2, yaml
   cams = yaml.safe_load(open("configs/local.yaml"))["cameras"]
   for name, c in cams.items():
       cap = cv2.VideoCapture(c["index"], cv2.CAP_AVFOUNDATION)
       cap.set(cv2.CAP_PROP_FRAME_WIDTH, c["width"])
       cap.set(cv2.CAP_PROP_FRAME_HEIGHT, c["height"])
       ok, frame, n, t = False, None, 0, time.time()
       while cap.isOpened() and time.time() - t < 2:
           got, f = cap.read()
           if got:
               ok, frame, n = True, f, n + 1
       cap.release()
       if ok:
           cv2.imwrite(f"{sys.argv[1]}/{name}.jpg", frame)
       print(name, c["index"], frame.shape if ok else "no frame", f"{n / 2:.0f} fps")
   EOF
   ```

   Expect about the configured fps. Wrong picture: camera fix below.
   Blurred: ask the owner to check for lens film and twist the lens.
3. **Power on (owner).** Ask: "Both supplies on, both arms resting in the
   same pose?" One word back.
4. **Alignment (agent).** `uv run so101-align`. Every joint `ok`: done.
   A joint OVER: name it and which way it is off, ask the owner to move the
   leader to match, and rerun on their "check". If a joint stays OVER while
   the arms look the same, recalibrate that arm (full path, step F4).
5. **Report.** One message: ports, camera, largest alignment gap, and the
   next command for the owner, usually:

   ```bash
   uv run so101-teleop --display
   ```

   with: clear the area and keep a hand near the follower's power. To stop,
   bring the follower to rest on the table, then press Ctrl-C once. LeRobot
   switches the follower's torque off when it disconnects, so it goes limp
   at once and falls if it is held up in the air.

## Fixes for a failed check

- **Port FAIL** (often a different USB socket). If `ls` shows two
  `usbmodem` ports, ask the owner to unplug the leader's USB cable; the port
  that disappears is the leader's. Edit `arms.<role>.port` in
  `configs/local.yaml`, ask them to plug it back in, rerun step 1. Fewer
  than two ports: a cable or board is not connected.
- **Camera FAIL or wrong picture.** Indices move when a camera is plugged
  in or an iPhone is near. Rerun the snapshot with indices 0 to 3 in place
  of the config (one `VideoCapture(i)` per `i` in 0-3, same loop), pick
  the frame with the gripper jaws, and set `index` in `configs/local.yaml`.
- **"camera access has been denied".** The terminal app lost its camera
  permission. OpenCV only checks it and never asks, so the owner runs this
  in their pane and clicks Allow (fixed it on 2026-10-23):

  ```bash
  tccutil reset Camera "${__CFBundleIdentifier:?unset: name the app, e.g. com.apple.Terminal}"
  printf '%s\n' 'import AVFoundation' 'let s = DispatchSemaphore(value: 0)' \
    'AVCaptureDevice.requestAccess(for: .video) { ok in print("granted:", ok); s.signal() }' \
    '_ = s.wait(timeout: .now() + 60)' > /tmp/camauth.swift
  swift /tmp/camauth.swift
  ```

  `granted: false` with no prompt: System Settings > Privacy & Security >
  Camera, switch the app on, restart it.
- **"rerun-sdk is required"** from `--display`: run `uv sync --dev
  --all-packages`. The `viz` extra is a dependency of hw-setup.

## Full path (first setup, reassembly or servo swap)

F1. Ports: ask the owner to run `uv run so101-find-ports` in their pane
(it prompts for each unplug); if they would rather not, do the port fix
above by hand, writing `configs/local.yaml` from
`configs/example.yaml`. Check it with
`so101.machine_config.parse_machine_config`.

F2. Doctor and camera: quick path steps 1 and 2.

F3. Power on and a "before" reading: quick path steps 3 and 4. Save the
reading for the record.

F4. Calibrate (owner's pane), follower first:

```bash
uv run so101-calibrate --role follower
uv run so101-calibrate --role leader
```

At the first prompt type `c` and ENTER: a bare ENTER writes the old file to
the motors. Middle pose: upright, elbow about 90 degrees, wrist straight,
gripper closed. Pose the leader exactly as the follower was, wrist rotated
the same way, because that pose sets the zero of both arms. Then each joint
except `wrist_roll` through its full range, and ENTER. Rerun quick path
step 4: every joint within 5 degrees (2026-10-23: largest 3.7). Commit the
new `hardware/calibration/<role>/main.json` on a branch.

F5. First teleop with the owner: `uv run so101-teleop --no-cameras`, then
`--display`, with the same hand-off as quick path step 5 (rest the
follower on the table before Ctrl-C).

Before any `so101-record`, rerun quick path steps 1 and 2: if the wrist
camera is unplugged, the recording silently uses whichever camera has its
index.

## Finish

Note anything that behaved differently from this skill or `docs/setup.md`,
and fix the skill in the same session.
