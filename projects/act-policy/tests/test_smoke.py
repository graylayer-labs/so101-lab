import act_policy
from so101 import JOINT_NAMES


def test_package_imports():
    assert act_policy.__doc__
    assert len(JOINT_NAMES) == 6
