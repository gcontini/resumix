"""The watched folder: what it claims and what it leaves alone."""

from __future__ import annotations

from resumix_client.sources.folder import FolderWatchSource
from resumix_client.workspace import Workspace


def drain(inbox, workspace):
    return list(FolderWatchSource(inbox, workspace, settle_seconds=0, once=True).candidates())


def test_files_and_folders_are_claimed_dot_entries_are_not(tmp_path):
    workspace = Workspace(tmp_path / "out").ensure()
    inbox = tmp_path / "in"
    (inbox / "job").mkdir(parents=True)
    (inbox / "job" / "jd.txt").write_text("a posting")
    (inbox / "posting.txt").write_text("another posting")
    (inbox / ".hidden").write_text("not mine")

    candidates = drain(inbox, workspace)

    by_label = {c.label: c for c in candidates}
    assert sorted(by_label) == ["job", "posting.txt"]
    assert by_label["job"].is_job_folder and by_label["job"].text == ""
    assert (by_label["job"].origin / "jd.txt").is_file()
    assert not by_label["posting.txt"].is_job_folder
    assert by_label["posting.txt"].text == "another posting"
    assert all(c.origin.parent == workspace.working for c in candidates)
    assert sorted(p.name for p in inbox.iterdir()) == [".hidden"]
