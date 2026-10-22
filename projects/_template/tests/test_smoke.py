import my_project
from so101 import JOINT_NAMES


def test_package_imports():
    assert my_project.__doc__
    assert len(JOINT_NAMES) == 6
