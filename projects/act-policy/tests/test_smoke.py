import socket

import pytest
import serial

import act_policy
from so101 import JOINT_NAMES


def test_package_imports():
    assert act_policy.__doc__
    assert len(JOINT_NAMES) == 6


def test_no_test_can_reach_the_network() -> None:
    with pytest.raises(AssertionError, match="network"):
        socket.create_connection(("huggingface.co", 443), timeout=1)


def test_no_test_can_open_a_serial_port() -> None:
    with pytest.raises(AssertionError, match="serial port"):
        serial.Serial("/dev/null")
