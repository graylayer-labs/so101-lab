"""Every calibration JSON committed under hardware/calibration/ must be sane."""

import json
from pathlib import Path

import pytest

from so101.calibration import CalibrationError, check_calibration, load_calibration


def find_repo_root(start: Path) -> Path:
    """Walk up from ``start`` to the directory holding the uv workspace pyproject."""
    for folder in (start, *start.parents):
        pyproject = folder / "pyproject.toml"
        if pyproject.is_file() and "[tool.uv.workspace]" in pyproject.read_text():
            return folder
    raise FileNotFoundError(f"no uv workspace pyproject.toml above {start}")


def discover_calibration_files(root: Path) -> list[Path]:
    """Every ``*.json`` under ``root/hardware/calibration``, sorted."""
    return sorted((root / "hardware" / "calibration").rglob("*.json"))


def verify_file(path: Path) -> None:
    check_calibration(load_calibration(path))


REPO_ROOT = find_repo_root(Path(__file__).resolve())
FILES = discover_calibration_files(REPO_ROOT)


@pytest.mark.parametrize(
    "path", FILES, ids=[str(p.relative_to(REPO_ROOT)) for p in FILES]
)
def test_committed_calibration_is_sane(path: Path):
    verify_file(path)


def test_no_files_present_discovers_nothing(tmp_path: Path):
    (tmp_path / "hardware" / "calibration" / "leader").mkdir(parents=True)
    assert discover_calibration_files(tmp_path) == []


def test_missing_calibration_folder_discovers_nothing(tmp_path: Path):
    assert discover_calibration_files(tmp_path) == []


def test_discovery_finds_nested_json_only(tmp_path: Path):
    folder = tmp_path / "hardware" / "calibration" / "leader"
    folder.mkdir(parents=True)
    (folder / "main.json").write_text("{}")
    (folder / ".gitkeep").write_text("")
    assert discover_calibration_files(tmp_path) == [folder / "main.json"]


def test_a_broken_copy_of_a_real_file_is_caught(tmp_path: Path):
    good = Path(__file__).parent / "fixtures" / "valid.json"
    raw = json.loads(good.read_text())
    raw["gripper"]["range_max"] = raw["gripper"]["range_min"] + 10
    bad = tmp_path / "broken.json"
    bad.write_text(json.dumps(raw))
    verify_file(good)
    with pytest.raises(CalibrationError, match="gripper"):
        verify_file(bad)
