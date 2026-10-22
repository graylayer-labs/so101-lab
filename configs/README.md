# Machine config

Settings that belong to one computer rather than to a project: which serial
port each arm is on and which camera index is which.

- `example.yaml` is committed and shows the shape.
- `local.yaml` is your real config. Copy `example.yaml` to `local.yaml` and
  edit it. It is gitignored, because ports and camera ids differ per machine.

Run configs for a project live in `projects/<name>/configs/`, not here.
