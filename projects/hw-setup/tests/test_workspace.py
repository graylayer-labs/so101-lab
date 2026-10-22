"""Tests for finding the workspace root and loading the machine config."""

from pathlib import Path

import pytest

from hw_setup.workspace import (
    WorkspaceError,
    find_workspace_root,
    load_local_config,
)

EXAMPLE = Path(__file__).parents[3] / "configs" / "example.yaml"


def make_workspace(tmp_path: Path) -> Path:
    (tmp_path / "hardware" / "calibration").mkdir(parents=True)
    (tmp_path / "configs").mkdir()
    return tmp_path


def test_finds_root_from_a_nested_folder(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    nested = root / "projects" / "x" / "src"
    nested.mkdir(parents=True)
    assert find_workspace_root(nested) == root.resolve()


def test_default_start_finds_this_workspace() -> None:
    root = find_workspace_root()
    assert (root / "hardware" / "calibration").is_dir()
    assert (root / "configs" / "example.yaml").is_file()


def test_no_root_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceError, match="workspace root"):
        find_workspace_root(tmp_path)


def test_missing_local_config_hints_at_the_fix(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    with pytest.raises(WorkspaceError) as err:
        load_local_config(root)
    text = str(err.value)
    assert str(root / "configs" / "local.yaml") in text
    assert "so101-find-ports" in text
    assert "configs/example.yaml" in text


def test_loads_local_config_from_the_root(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    (root / "configs" / "local.yaml").write_text(EXAMPLE.read_text())
    config = load_local_config(root)
    assert set(config.arms) == {"leader", "follower"}


def test_explicit_config_path_is_used(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    other = tmp_path / "other.yaml"
    other.write_text(EXAMPLE.read_text())
    assert load_local_config(root, other).cameras


def test_missing_explicit_config_is_an_error(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    with pytest.raises(WorkspaceError, match="nope.yaml"):
        load_local_config(root, tmp_path / "nope.yaml")


def test_invalid_config_is_a_workspace_error(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    bad = root / "configs" / "local.yaml"
    bad.write_text("arms: 3\n")
    with pytest.raises(WorkspaceError, match="local.yaml"):
        load_local_config(root)
