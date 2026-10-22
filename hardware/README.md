# Hardware

Files that describe the physical arms. Nothing here is Python source: code
that reads these files lives in `shared/so101/` or a project.

| Folder | What lives there |
|---|---|
| `calibration/` | Per-arm calibration JSON, one folder per role (`leader/`, `follower/`). |
| `urdf/` | Robot description (URDF or MJCF) and meshes, for simulation and kinematics. |
| `cad/` | Printed parts, mounts and camera brackets (STEP, STL, 3MF), stored with Git LFS. |
| `bom.md` | Bill of materials. |

## Calibration files

Name each file after the arm it belongs to:
`calibration/<role>/<arm_id>.json`, for example
`calibration/follower/main.json`. The `arm_id` is the id passed to LeRobot
(`--robot.id` / `--teleop.id`), so the same name works in both places. Copy
the file in after running LeRobot's calibration; it uses LeRobot's JSON
layout, and `so101.load_calibration` checks it. Recalibrate, and replace the
file, after reassembling an arm or replacing a servo.

## URDF and meshes

The SO-101 description comes from the upstream
[SO-ARM100 repository](https://github.com/TheRobotStudio/SO-ARM100)
(`Simulation/SO101/`). It is not vendored yet: copy only the files a project
needs, note the upstream commit next to them, and put meshes through Git LFS
if they are large.

## CAD

`*.stl`, `*.step`, `*.stp` and `*.3mf` files are tracked with Git LFS (see
`.gitattributes`). Run `git lfs install` once per machine before adding any.
