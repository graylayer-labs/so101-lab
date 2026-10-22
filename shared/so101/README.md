# so101

Code that more than one project needs: the SO-101 joint names, a typed arm
config, and loading of per-arm calibration files from `hardware/calibration/`.

```python
from pathlib import Path

from so101 import ArmRole, calibration_path, load_calibration

path = calibration_path(Path("hardware/calibration"), ArmRole.FOLLOWER, "main")
calib = load_calibration(path)  # dict of joint name -> JointCalibration
```

The calibration file uses the JSON layout LeRobot writes for the SO-101: one
object per joint with `id`, `drive_mode`, `homing_offset`, `range_min` and
`range_max`. Ranges are raw STS3215 encoder counts, 0 to 4095.

To compare two calibrations, `diff_calibrations(old, new)` lists every changed
`id`, `homing_offset`, `range_min`, `range_max` and `drive_mode` per joint,
plus added and removed joints; `format_diff` prints it as a table.

Add code here only when a second project needs it. Until then it stays in the
project that uses it.
