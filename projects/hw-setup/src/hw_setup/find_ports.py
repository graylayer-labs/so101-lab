"""Find the serial port of each arm and write them to ``configs/local.yaml``.

Replaces a blind wrap of ``lerobot-find-port``. In lerobot 0.6.1 that script
globs ``/dev/tty*`` and blocks on ``input()`` for one board at a time, so it
cannot run under a test or a script, and it does not write anything. Here the
ports come from pyserial's ``list_ports.comports()``, which reads the system's
device list and never opens a port. The owner unplugs and replugs each arm in
turn; the port that disappears is that arm's port.

On macOS pyserial lists ``/dev/cu.usbmodem*``; LeRobot accepts either the
``cu`` or the ``tty`` name, and the machine config validator accepts both.
"""

import argparse
import sys
import time
from collections.abc import Callable
from pathlib import Path

import yaml

from so101 import ArmRole, MachineConfigError
from so101.machine_config import parse_machine_config

PortLister = Callable[[], list[str]]
InputFn = Callable[[str], str]
SleepFn = Callable[[float], None]

# Time for the OS to drop or restore the device after the cable moves.
SETTLE_SECONDS = 0.5
REPLUG_TRIES = 10
ROLES = (ArmRole.LEADER, ArmRole.FOLLOWER)


class FindPortsError(RuntimeError):
    """The unplug/replug diff did not point at exactly one port."""


def list_serial_ports() -> list[str]:
    """Serial devices known to the system. Does not open any of them."""
    from serial.tools import list_ports

    return sorted(p.device for p in list_ports.comports())


def find_ports(
    lister: PortLister = list_serial_ports,
    input_fn: InputFn = input,
    sleep: SleepFn = time.sleep,
) -> dict[ArmRole, str]:
    """Ask the owner to unplug and replug each arm; return role -> port."""
    found: dict[ArmRole, str] = {}
    for role in ROLES:
        before = set(lister())
        input_fn(f"Unplug the USB cable of the {role.value} arm, then press Enter. ")
        sleep(SETTLE_SECONDS)
        gone = sorted(before - set(lister()))
        if not gone:
            raise FindPortsError(
                f"{role.value}: no port disappeared; is it plugged in?"
            )
        if len(gone) > 1:
            raise FindPortsError(
                f"{role.value}: more than one port disappeared ({', '.join(gone)})"
            )
        port = gone[0]
        input_fn(f"Plug the {role.value} arm back in, then press Enter. ")
        for _ in range(REPLUG_TRIES):
            sleep(SETTLE_SECONDS)
            if port in lister():
                break
        else:
            raise FindPortsError(f"{role.value}: {port} did not come back after replug")
        found[role] = port
    if len(set(found.values())) != len(found):
        raise FindPortsError(f"both arms gave the same port: {found}")
    return found


def merge_ports(data: object, ports: dict[ArmRole, str]) -> dict:
    """Set ``arms.<role>.port`` in parsed config data, keeping everything else."""
    if not isinstance(data, dict) or not isinstance(data.get("arms"), dict):
        raise FindPortsError("config has no 'arms' mapping")
    for role, port in ports.items():
        arm = data["arms"].setdefault(role.value, {})
        if not isinstance(arm, dict):
            raise FindPortsError(f"arms.{role.value} is not a mapping")
        arm["port"] = port
    return data


def _default_example() -> Path:
    for parent in (Path.cwd(), *Path.cwd().parents):
        if (parent / "configs" / "example.yaml").is_file():
            return parent / "configs" / "example.yaml"
    return Path("configs/example.yaml")


def _read_base(config: Path, example: Path) -> tuple[object, bool]:
    """Parsed YAML to update, and whether the file will be newly created."""
    source, created = (config, False) if config.exists() else (example, True)
    if not source.exists():
        raise FindPortsError(f"{source}: not found")
    return yaml.safe_load(source.read_text()), created


def _dry_run(config: Path, example: Path) -> None:
    created = not config.exists()
    print("Dry run: nothing is read, listed, opened or written.")
    print("Would do, for the leader arm and then the follower arm:")
    print("  1. list ports with serial.tools.list_ports.comports() (opens none)")
    print("  2. ask you to unplug that arm's USB cable, then list again")
    print("  3. ask you to plug it back in and check the port returns")
    print("  4. the one port that disappeared is that arm's port")
    print("(lerobot-find-port is not run: it blocks on input() and writes nothing.)")
    action = f"create it from {example}" if created else "update it, keeping other keys"
    print(f"Would write {config} ({action}), setting:")
    for role in ROLES:
        print(f"  arms.{role.value}.port = <port found for the {role.value} arm>")
    print("The result is checked with so101.machine_config before it is written.")


def main(
    argv: list[str] | None = None,
    lister: PortLister = list_serial_ports,
    input_fn: InputFn = input,
    sleep: SleepFn = time.sleep,
) -> int:
    parser = argparse.ArgumentParser(
        prog="so101-find-ports",
        description="Find each arm's serial port and write it to configs/local.yaml.",
    )
    parser.add_argument("--dry-run", action="store_true", help="print the plan only")
    parser.add_argument("--config", type=Path, default=Path("configs/local.yaml"))
    parser.add_argument("--example", type=Path, default=None)
    args = parser.parse_args(argv)
    example = args.example or _default_example()

    if args.dry_run:
        _dry_run(args.config, example)
        return 0
    try:
        data, _created = _read_base(args.config, example)
        ports = find_ports(lister, input_fn, sleep)
        merged = merge_ports(data, ports)
        parse_machine_config(merged)
    except (FindPortsError, MachineConfigError) as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    args.config.parent.mkdir(parents=True, exist_ok=True)
    args.config.write_text(yaml.safe_dump(merged, sort_keys=False))
    for role, port in ports.items():
        print(f"{role.value}: {port}")
    print(f"Wrote {args.config}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
