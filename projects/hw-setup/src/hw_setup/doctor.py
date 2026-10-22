"""``so101-doctor``: a read-only preflight for the SO-101 setup.

It reports PASS, WARN or FAIL for each check, with a concrete fix for every
FAIL and WARN, and changes nothing. It is useful with no arm attached.

- It never opens a serial port: ports come from pyserial's
  ``list_ports.comports()`` (see ``hw_setup.find_ports``).
- It never runs LeRobot.
- Cameras are only listed unless ``--open-cameras`` is given. LeRobot's own
  enumeration (``OpenCVCamera.find_cameras``, lerobot 0.6.1
  ``cameras/opencv/camera_opencv.py`` L330) calls ``cv2.VideoCapture(target)``
  on every index, which opens each device and triggers the macOS permission
  prompt, so it is not used. The default list comes from ``system_profiler
  SPCameraDataType -json`` on macOS and ``/dev/video*`` on Linux; neither
  opens a camera.
- It does not compare parsed ``type`` strings of LeRobot configs: ``so101_*``
  and ``so100_*`` parse to the same classes.
"""

import argparse
import importlib.metadata
import json
import platform as platform_module
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from hw_setup.find_ports import list_serial_ports
from hw_setup.teleop import calibration_problems
from hw_setup.workspace import WorkspaceError, find_workspace_root, load_local_config
from so101.arm import ArmRole
from so101.machine_config import MachineConfig

LEROBOT_PIN = "0.6.1"  # must match projects/hw-setup/pyproject.toml
MIN_PYTHON = (3, 12)
PERMISSION_HINT = (
    "grant camera access: System Settings > Privacy & Security > Camera, "
    "switch on the terminal app you run this from, then restart it"
)

PortLister = Callable[[], list[str]]
VersionGetter = Callable[[], str | None]
CameraLister = Callable[[], list[str]]
CameraOpener = Callable[[int], str | None]  # None = opened and read a frame


@dataclass
class Result:
    status: str  # PASS, WARN or FAIL
    name: str
    summary: str
    details: list[str] = field(default_factory=list)
    fixes: list[str] = field(default_factory=list)


def lerobot_version() -> str | None:
    try:
        return importlib.metadata.version("lerobot")
    except importlib.metadata.PackageNotFoundError:
        return None


def parse_system_profiler(text: str) -> list[str]:
    """Camera names from ``system_profiler SPCameraDataType -json`` output."""
    try:
        items = json.loads(text).get("SPCameraDataType", [])
        return [str(item["_name"]) for item in items]
    except (ValueError, AttributeError, KeyError, TypeError):
        return []


def list_cameras() -> list[str]:
    """Camera names the OS knows about, without opening any of them."""
    system = platform_module.system()
    if system == "Darwin":
        try:
            done = subprocess.run(
                ["system_profiler", "SPCameraDataType", "-json"],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return []
        return parse_system_profiler(done.stdout)
    if system == "Linux":
        return sorted(str(p) for p in Path("/dev").glob("video*"))
    return []


def open_camera(index: int) -> str | None:
    """Open OpenCV camera ``index``, read one frame, release it."""
    import cv2

    capture = cv2.VideoCapture(index)
    try:
        if not capture.isOpened():
            return "could not open it"
        ok, _frame = capture.read()
        return None if ok else "opened but could not read a frame"
    finally:
        capture.release()


def check_python() -> Result:
    have = ".".join(map(str, sys.version_info[:3]))
    if sys.version_info[:2] < MIN_PYTHON:
        need = ".".join(map(str, MIN_PYTHON))
        return Result(
            "FAIL", "python", f"{have}, need >= {need}",
            fixes=["uv sync --dev --all-packages  (uv fetches a matching Python)"],
        )  # fmt: skip
    return Result("PASS", "python", have)


def check_lerobot(getter: VersionGetter) -> Result:
    have = getter()
    fix = ["uv sync --dev --all-packages"]
    if have is None:
        return Result("FAIL", "lerobot", "not installed", fixes=fix)
    if have != LEROBOT_PIN:
        return Result(
            "FAIL", "lerobot", f"{have} installed, pinned {LEROBOT_PIN}", fixes=fix
        )
    return Result("PASS", "lerobot", f"{have} (pinned)")


def _skipped(name: str) -> Result:
    return Result("WARN", name, "skipped: no valid machine config")


def check_ports(
    config: MachineConfig, lister: PortLister, platform_name: str
) -> Result:
    present = set(lister())
    details: list[str] = []
    fixes: list[str] = []
    status = "PASS"
    for role in ArmRole:
        port = config.arms[role].port
        if port not in present:
            status = "FAIL"
            details.append(f"{role.value}: {port} not found")
            continue
        if platform_name == "darwin" and port.startswith("/dev/tty."):
            cu = "/dev/cu." + port.removeprefix("/dev/tty.")
            if status == "PASS":
                status = "WARN"
            details.append(
                f"{role.value}: {port} is a tty.* name; the cu.* name {cu} is the "
                "usual choice on macOS (LeRobot accepts both)"
            )
        else:
            details.append(f"{role.value}: {port} found")
    if status == "FAIL":
        fixes.append(
            "plug in both arms and run: so101-find-ports  "
            "(or fix arms.<role>.port in configs/local.yaml)"
        )
    elif status == "WARN":
        fixes.append("optional: set the cu.* name in configs/local.yaml")
    shown = sorted(present) or ["none"]
    details.append("listed by pyserial: " + ", ".join(shown))
    summary = {
        "PASS": "both arm ports present",
        "WARN": "ports present, tty.* name used",
        "FAIL": "an arm port is not present",
    }[status]
    return Result(status, "ports", summary, details, fixes)


def check_calibrations(config: MachineConfig, root: Path) -> Result:
    problems = calibration_problems(config, root)
    if not problems:
        return Result("PASS", "calibration", "leader and follower pass the checks")
    fixes = []
    for role in ArmRole:
        if any(p.startswith(f"{role.value} arm") for p in problems):
            fixes.append(f"so101-calibrate --role {role.value}")
    return Result("FAIL", "calibration", f"{len(problems)} problem(s)", problems, fixes)


def check_cameras(
    config: MachineConfig,
    lister: CameraLister,
    opener: CameraOpener,
    platform_name: str,
    open_cameras: bool,
) -> Result:
    found = lister()
    configured = len(config.cameras)
    details = [f"listed by the OS: {', '.join(found) if found else 'none'}"]
    status = "PASS"
    summary = f"{len(found)} listed, {configured} configured"
    fixes: list[str] = []
    if len(found) < configured:
        status = "WARN"
        fixes.append("connect the cameras, or edit cameras in configs/local.yaml")
    if open_cameras:
        for name, cam in config.cameras.items():
            error = opener(cam.index)
            if error is None:
                details.append(f"{name} (index {cam.index}): opened, frame read")
                continue
            status = "FAIL"
            details.append(f"{name} (index {cam.index}): {error}")
        if status == "FAIL":
            summary = "a configured camera did not open"
            fixes.append("check the cable and that no other app uses the camera")
            if platform_name == "darwin":
                fixes.append(PERMISSION_HINT)
    else:
        details.append("not opened; add --open-cameras to open each configured index")
    return Result(status, "cameras", summary, details, fixes)


def run_checks(
    root: Path | None,
    config_path: Path | None,
    open_cameras: bool,
    port_lister: PortLister,
    version_getter: VersionGetter,
    camera_lister: CameraLister,
    camera_opener: CameraOpener,
    platform_name: str,
) -> list[Result]:
    results = [check_python(), check_lerobot(version_getter)]
    config: MachineConfig | None = None
    try:
        workspace = root if root is not None else find_workspace_root()
        results.append(Result("PASS", "workspace", str(workspace)))
    except WorkspaceError as err:
        results.append(
            Result("FAIL", "workspace", str(err), fixes=["run from inside so101-lab"])
        )
        workspace = None
    if workspace is not None:
        try:
            config = load_local_config(workspace, config_path)
            target = config_path or workspace / "configs" / "local.yaml"
            results.append(Result("PASS", "config", f"{target} is valid"))
        except WorkspaceError as err:
            results.append(
                Result(
                    "FAIL",
                    "config",
                    str(err),
                    fixes=[
                        "so101-find-ports  (writes configs/local.yaml)",
                        "or: cp configs/example.yaml configs/local.yaml  and edit it",
                    ],
                )  # fmt: skip
            )
    if config is None or workspace is None:
        return [
            *results,
            _skipped("ports"),
            _skipped("calibration"),
            _skipped("cameras"),
        ]
    results.append(check_ports(config, port_lister, platform_name))
    results.append(check_calibrations(config, workspace))
    results.append(
        check_cameras(config, camera_lister, camera_opener, platform_name, open_cameras)
    )
    return results


def format_results(results: list[Result]) -> str:
    lines = []
    for r in results:
        lines.append(f"{r.status:<4}  {r.name}: {r.summary}")
        lines.extend(f"        {d}" for d in r.details)
        if r.status != "PASS":
            lines.extend(f"        fix: {f}" for f in r.fixes)
    return "\n".join(lines)


def main(
    argv: Sequence[str] | None = None,
    *,
    root: Path | None = None,
    port_lister: PortLister = list_serial_ports,
    version_getter: VersionGetter = lerobot_version,
    camera_lister: CameraLister = list_cameras,
    camera_opener: CameraOpener = open_camera,
    platform: str = sys.platform,
) -> int:
    parser = argparse.ArgumentParser(
        prog="so101-doctor",
        description="Check the setup. Reports only; opens no serial port.",
    )
    parser.add_argument(
        "--config", type=Path, help="machine config (default: configs/local.yaml)"
    )
    parser.add_argument(
        "--open-cameras",
        action="store_true",
        help="open each configured camera and read a frame (default: only list)",
    )
    args = parser.parse_args(argv)
    results = run_checks(
        root, args.config, args.open_cameras, port_lister, version_getter,
        camera_lister, camera_opener, platform,
    )  # fmt: skip
    print(format_results(results))
    failed = [r.name for r in results if r.status == "FAIL"]
    if failed:
        print(f"\n{len(failed)} failed: {', '.join(failed)}")
    else:
        print("\nNothing failed.")
    return 1 if failed else 0


def cli() -> None:
    sys.exit(main())
