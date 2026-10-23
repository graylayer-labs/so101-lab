"""Shared fakes for the SO-101 arms. No test may open a serial port.

``FakeFeetechBus`` subclasses LeRobot 0.6.1's real ``FeetechMotorsBus`` and
replaces only the lowest layer, the methods that talk to the serial port
through ``scservo_sdk``. Everything above them is LeRobot's own code, so the
return shapes and units are the real ones: ``connect``, ``disconnect``,
``sync_read`` (sign decode and ``_normalize``), ``read`` and
``is_calibrated``. The replaced methods, with their real signatures
(paths relative to ``site-packages/lerobot``):

- ``port_handler``: an ``scservo_sdk.PortHandler``; LeRobot uses ``is_open``,
  ``is_using``, ``openPort()``, ``closePort()``, ``clearPort()`` and
  ``setPacketTimeoutMillis(msec)`` on connect and disconnect
  (motors/motors_bus.py L511, L532, L557-561, L701).
- ``_handshake(self) -> None`` (motors/feetech/feetech.py L155): pings each
  id and reads firmware; recorded, no packets.
- ``_sync_read(self, addr, length, motor_ids, *, num_retry=0,
  raise_on_error=True, err_msg="") -> tuple[dict[int, int], int]``
  (motors/motors_bus.py L1173): raw register values by motor id, and the
  comm result.
- ``_read(self, address, length, motor_id, *, num_retry=0,
  raise_on_error=True, err_msg="") -> tuple[int, int, int]``
  (motors/motors_bus.py L1031): value, comm, error.
- ``_write(self, addr, length, motor_id, value, *, num_retry=0,
  raise_on_error=True, err_msg="") -> tuple[int, int]`` (L1099) and
  ``_sync_write(self, addr, length, ids_values, num_retry=0,
  raise_on_error=True, err_msg="") -> int`` (L1262): every write, torque
  and goal included, ends here, so both are recorded by register name.

Raw ``Present_Position`` values are encoder ticks, 0-4095 on the STS3215
(motors/feetech/tables.py ``MODEL_RESOLUTION``). LeRobot turns them into
degrees with ``(raw - (range_min + range_max) / 2) * 360 / 4095`` for the
body joints and into ``0-100`` % of the calibrated range for the gripper
(motors/motors_bus.py L854-881).
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import serial
from lerobot.motors import Motor, MotorCalibration
from lerobot.motors.feetech import FeetechMotorsBus
from scservo_sdk import COMM_SUCCESS

from hw_setup import align
from so101.arm import ArmRole
from so101.machine_config import MachineConfig

JOINTS = (
    "shoulder_pan",
    "shoulder_lift",
    "elbow_flex",
    "wrist_flex",
    "wrist_roll",
    "gripper",
)


@pytest.fixture(autouse=True)
def no_serial_port(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail any test that reaches pyserial's open, the last step to a port."""

    def refuse(self: object, *args: object, **kwargs: object) -> None:
        raise AssertionError("a test tried to open a serial port")

    monkeypatch.setattr(serial.Serial, "open", refuse)


class FakePortHandler:
    """The members of ``scservo_sdk.PortHandler`` LeRobot's bus touches."""

    def __init__(self, port_name: str) -> None:
        self.port_name = port_name
        self.is_open = False
        self.is_using = False
        self.open_ok = True
        self.calls: list[str] = []

    def openPort(self) -> bool:  # noqa: N802 - scservo_sdk's name
        self.calls.append("openPort")
        self.is_open = self.open_ok
        return self.open_ok

    def closePort(self) -> None:  # noqa: N802
        self.calls.append("closePort")
        self.is_open = False

    def clearPort(self) -> None:  # noqa: N802
        self.calls.append("clearPort")

    def setPacketTimeoutMillis(self, msec: int) -> None:  # noqa: N802
        self.calls.append(f"setPacketTimeoutMillis({msec})")


class FakeFeetechBus(FeetechMotorsBus):
    """LeRobot's real Feetech bus with the serial layer replaced.

    ``raw`` holds raw ``Present_Position`` ticks per motor name. The motors'
    stored calibration registers default to the file's values, so
    ``is_calibrated`` is True unless ``motor_calibration`` says otherwise.
    """

    def __init__(
        self,
        port: str,
        motors: dict[str, Motor],
        calibration: dict[str, MotorCalibration],
        *,
        raw: dict[str, int],
        motor_calibration: dict[str, MotorCalibration] | None = None,
        fail_sync_read: Exception | None = None,
        open_ok: bool = True,
    ) -> None:
        super().__init__(port, motors, calibration)
        handler = FakePortHandler(port)
        handler.open_ok = open_ok
        self.port_handler = handler  # ty: ignore[invalid-assignment]
        self.raw = dict(raw)
        self.motor_calibration = motor_calibration or calibration
        self.fail_sync_read = fail_sync_read
        self.handshakes = 0
        self.writes: list[tuple[str, int, int]] = []  # (register, id, value)
        self.sync_reads: list[str] = []
        self._names_by_addr = {
            addr: name
            for name, (addr, _len) in self.model_ctrl_table["sts3215"].items()
        }

    def _register(self, addr: int) -> str:
        return self._names_by_addr[addr]

    def _handshake(self) -> None:
        self.handshakes += 1

    def _sync_read(
        self,
        addr: int,
        length: int,
        motor_ids: list[int],
        *,
        num_retry: int = 0,
        raise_on_error: bool = True,
        err_msg: str = "",
    ) -> tuple[dict[int, int], int]:
        name = self._register(addr)
        self.sync_reads.append(name)
        if self.fail_sync_read is not None:
            raise self.fail_sync_read
        if name != "Present_Position":
            raise NotImplementedError(name)
        return {i: self.raw[self._id_to_name(i)] for i in motor_ids}, COMM_SUCCESS

    def _read(
        self,
        address: int,
        length: int,
        motor_id: int,
        *,
        num_retry: int = 0,
        raise_on_error: bool = True,
        err_msg: str = "",
    ) -> tuple[int, int, int]:
        name = self._register(address)
        cal = self.motor_calibration[self._id_to_name(motor_id)]
        values = {
            "Homing_Offset": cal.homing_offset,
            "Min_Position_Limit": cal.range_min,
            "Max_Position_Limit": cal.range_max,
        }
        # Registers hold sign-magnitude values; LeRobot decodes them after.
        encoded = self._encode_sign(name, {motor_id: values[name]})[motor_id]
        return encoded, COMM_SUCCESS, 0

    def _write(
        self,
        addr: int,
        length: int,
        motor_id: int,
        value: int,
        *,
        num_retry: int = 0,
        raise_on_error: bool = True,
        err_msg: str = "",
    ) -> tuple[int, int]:
        self.writes.append((self._register(addr), motor_id, value))
        return COMM_SUCCESS, 0

    def _sync_write(
        self,
        addr: int,
        length: int,
        ids_values: dict[int, int],
        num_retry: int = 0,
        raise_on_error: bool = True,
        err_msg: str = "",
    ) -> int:
        for motor_id, value in ids_values.items():
            self.writes.append((self._register(addr), motor_id, value))
        return COMM_SUCCESS


def raw_for(bus: FeetechMotorsBus, values: dict[str, float]) -> dict[str, int]:
    """Raw ticks that LeRobot reads back as ``values`` (degrees or %).

    The inverse of ``_normalize``, from the bus's calibration and the real
    ``_unnormalize`` (motors/motors_bus.py L883-911).
    """
    ids = {bus.motors[name].id: value for name, value in values.items()}
    raw = bus._unnormalize(ids)
    return {bus._id_to_name(i): v for i, v in raw.items()}


Positions = dict[str, float]
MakeArms = Callable[..., tuple[align.DeviceFactory, dict[ArmRole, Any]]]
REAL_MAKE_DEVICES = align.make_devices


@pytest.fixture
def fake_arms() -> MakeArms:
    """Build the real LeRobot leader and follower, then swap in fake buses.

    ``make(leader=..., follower=..., <bus option>={role: value})`` takes
    per-joint positions in LeRobot's units (default: every joint at 0) and
    returns ``(factory, devices)``. The factory builds the devices with the
    real ``align.make_devices`` (no port is opened), then replaces each
    ``device.bus`` with a ``FakeFeetechBus`` on the same motors and
    calibration. ``devices[role].bus`` is that fake, for assertions.
    """

    def make(
        leader: Positions | None = None,
        follower: Positions | None = None,
        **bus_options: dict[ArmRole, Any],
    ) -> tuple[align.DeviceFactory, dict[ArmRole, Any]]:
        poses = {ArmRole.LEADER: leader or {}, ArmRole.FOLLOWER: follower or {}}
        built: dict[ArmRole, Any] = {}

        def factory(config: MachineConfig, root: Path) -> dict[ArmRole, Any]:
            devices = REAL_MAKE_DEVICES(config, root)
            for role, device in devices.items():
                real = device.bus
                pose = dict.fromkeys(JOINTS, 0.0) | poses[role]
                options = {k: v[role] for k, v in bus_options.items() if role in v}
                device.bus = FakeFeetechBus(
                    real.port,
                    real.motors,
                    real.calibration,
                    raw=raw_for(real, pose),
                    **options,
                )
            built.update(devices)
            return devices

        return factory, built

    return make


@pytest.fixture(autouse=True)
def aligned_by_default(monkeypatch: pytest.MonkeyPatch, fake_arms: MakeArms) -> None:
    """Commands that run the alignment check see two matching fake arms."""
    factory, _ = fake_arms()
    monkeypatch.setattr(align, "make_devices", factory)
