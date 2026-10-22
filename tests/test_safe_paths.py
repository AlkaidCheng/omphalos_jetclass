from pathlib import Path

import pytest

from omphjc.safe_paths import (
    inside,
    normalize_path,
    plain_name,
    remove_inside,
    working_directory,
)

UNSAFE_NAMES = [
    "",
    ".",
    "..",
    "../x",
    "/etc",
    "a/b",
    "a\\b",
    "my run",
    "-rf",
    ".hidden",
]


@pytest.mark.parametrize(
    "name", ["HToBB", "ZJetsToNuNu", "heft_c_mass", "run-2", "v1.2"]
)
def test_plain_names_are_accepted(name: str) -> None:
    assert plain_name(name) == name


@pytest.mark.parametrize("name", UNSAFE_NAMES)
def test_names_that_could_leave_a_directory_are_refused(name: str) -> None:
    with pytest.raises(ValueError, match="Process name"):
        plain_name(name, what="Process name")


def test_normalize_path_expands_home_and_resolves_parents_and_links(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "real").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "real")
    expected = (tmp_path / "real").resolve()
    assert normalize_path("~/link/../real") == expected
    assert normalize_path(tmp_path / "link") == expected


def test_a_filesystem_root_is_no_working_directory(tmp_path: Path) -> None:
    assert working_directory(tmp_path / "run") == (tmp_path / "run").resolve()
    for root in ("/", "/..", "//"):
        with pytest.raises(ValueError, match="filesystem root"):
            working_directory(root)


def test_inside_joins_plain_names_only(tmp_path: Path) -> None:
    assert inside(tmp_path, "models", "heft") == tmp_path / "models" / "heft"
    for name in UNSAFE_NAMES:
        with pytest.raises(ValueError, match="Path component"):
            inside(tmp_path, "models", name)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    root = tmp_path / "root"
    (root / "tree" / "branch").mkdir(parents=True)
    (root / "tree" / "branch" / "leaf.txt").write_text("leaf")
    (root / "file.txt").write_text("file")
    (tmp_path / "outside.txt").write_text("outside")
    return root


def test_files_and_trees_inside_the_root_are_removed(root: Path) -> None:
    remove_inside(root, [root / "tree", root / "file.txt", root / "missing"])
    assert list(root.iterdir()) == []


@pytest.mark.parametrize("name", ["", ".", "..", "tree/../..", "/"])
def test_the_root_and_paths_outside_it_are_refused(root: Path, name: str) -> None:
    with pytest.raises(ValueError, match="not inside"):
        remove_inside(root, [root / "file.txt", root / name])
    assert (root / "file.txt").is_file()
    assert (root.parent / "outside.txt").is_file()


def test_symbolic_links_are_refused_and_their_targets_kept(root: Path) -> None:
    (root / "link").symlink_to(root.parent / "outside.txt")
    (root / "dir_link").symlink_to(root.parent)
    for link in ("link", "dir_link"):
        with pytest.raises(ValueError, match="symbolic link"):
            remove_inside(root, [root / link])
    assert (root.parent / "outside.txt").read_text() == "outside"


def test_a_path_through_a_linked_folder_outside_is_refused(root: Path) -> None:
    (root / "via").symlink_to(root.parent)
    with pytest.raises(ValueError, match="not inside"):
        remove_inside(root, [root / "via" / "outside.txt"])
    assert (root.parent / "outside.txt").is_file()


def test_links_inside_a_removed_tree_are_not_followed(root: Path) -> None:
    (root / "tree" / "link").symlink_to(root.parent / "outside.txt")
    remove_inside(root, [root / "tree"])
    assert (root.parent / "outside.txt").read_text() == "outside"
