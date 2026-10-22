# Scripts

Setup scripts. Each one is a thin wrapper around a LeRobot CLI that reads ports
and arm ids from `configs/local.yaml`, so nobody has to retype them. The ones
marked built are console scripts in `projects/hw-setup`; the rest arrive with
the first project that needs them.

| Script | Wraps | What it does |
|---|---|---|
| `find_ports` | pyserial `list_ports` | Finds the serial port of each arm's controller board. Built: `uv run so101-find-ports` (see `projects/hw-setup/README.md`). |
| `setup_motors` | `lerobot-setup-motors` | Sets the id and baud rate of each servo, one at a time. |
| `calibrate` | `lerobot-calibrate` | Calibrates one arm and copies the result to `hardware/calibration/<role>/<arm_id>.json`. |
| `teleop` | `lerobot-teleoperate` | Drives the follower from the leader, optionally with cameras. |

Scripts hold no logic of their own. Anything reusable goes in
`shared/so101/`, with tests.
