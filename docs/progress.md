# Progress

Newest first. One entry per merged task or chunk.

## 2026-10-22 · Repo scaffolded for the SO-101 arm

There is now one place for everything about the SO-101 arms: a uv workspace
with a shared `so101` package, a copyable project template, and folders for
calibration files, URDF, CAD and the bill of materials. The shared package
can already read and check a LeRobot calibration file, so a bad or partial
calibration is caught before it reaches a servo. No hardware has been
connected yet.
