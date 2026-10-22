import hw_setup
from so101 import JOINT_NAMES


def test_package_imports():
    assert hw_setup.__doc__
    assert len(JOINT_NAMES) == 6
