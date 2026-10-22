"""Find the so101-lab workspace root and load its machine config.

Shared by the ``so101-*`` console scripts. The root is the folder that has
``hardware/calibration/``: the same test ``lerobot_argv.calibration_dir`` uses
to accept a root. It is found by walking up from this file, not from the
current directory, so the scripts work from anywhere.
"""

from pathlib import Path

from hw_setup.lerobot_argv import CALIBRATION_ROOT
from so101.machine_config import MachineConfig, MachineConfigError, load_machine_config

LOCAL_CONFIG = Path("configs") / "local.yaml"


class WorkspaceError(Exception):
    """The workspace or its machine config cannot be used."""


def find_workspace_root(start: Path | None = None) -> Path:
    """The nearest folder at or above ``start`` with ``hardware/calibration/``.

    ``start`` defaults to this file's folder, not the current directory.
    """
    here = (start if start is not None else Path(__file__).parent).resolve()
    for folder in (here, *here.parents):
        if (folder / CALIBRATION_ROOT).is_dir():
            return folder
    raise WorkspaceError(
        f"no workspace root found above {here} (no {CALIBRATION_ROOT}/ folder)"
    )


def load_local_config(root: Path, path: Path | None = None) -> MachineConfig:
    """Load ``path``, or ``<root>/configs/local.yaml`` when it is None.

    A missing default is an error with a hint; it never falls back to the
    example config.
    """
    target = path if path is not None else root / LOCAL_CONFIG
    if not target.is_file():
        hint = ""
        if path is None:
            hint = (
                " Run so101-find-ports, or copy configs/example.yaml to "
                "configs/local.yaml and edit it."
            )
        raise WorkspaceError(f"machine config not found: {target}.{hint}")
    try:
        return load_machine_config(target)
    except MachineConfigError as err:
        raise WorkspaceError(f"{target}: {err}") from err
