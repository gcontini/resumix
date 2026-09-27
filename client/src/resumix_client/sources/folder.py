"""A watched folder as a source of job descriptions."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Iterator, Optional, Tuple

from . import JDCandidate
from ..workspace import Workspace

POLL_SECONDS = 2.0
#: A file whose size stopped changing for this long is finished being written.
SETTLE_SECONDS = 1.0


def read_text(path: Path) -> str:
    """Read whatever is there. Binary payloads are rejected downstream, so
    they must survive the read rather than raise."""
    return path.read_bytes().decode("utf-8", errors="replace")


class FolderWatchSource:
    """Yields every file or job folder dropped into ``inbox``, claiming it immediately.

    Claiming first is the whole trick: the file leaves the watched folder the
    moment it is seen, so nothing is ever processed twice and a crash leaves
    it in ``working/`` where the recovery prompt can find it.
    """

    def __init__(
        self,
        inbox: Path,
        workspace: Workspace,
        *,
        poll_seconds: float = POLL_SECONDS,
        settle_seconds: float = SETTLE_SECONDS,
        once: bool = False,
    ) -> None:
        self.inbox = Path(inbox)
        self.workspace = workspace
        self.poll_seconds = poll_seconds
        self.settle_seconds = settle_seconds
        self.once = once

    def candidates(self) -> Iterator[JDCandidate]:
        while True:
            for path in sorted(self.inbox.iterdir()) if self.inbox.is_dir() else []:
                if path.name.startswith("."):
                    continue
                if not self._settled(path):
                    continue
                claimed = self.workspace.take_in(path)
                print(f"📥 {path.name} -> working/{claimed.name}", flush=True)
                text = "" if claimed.is_dir() else read_text(claimed)
                yield JDCandidate(text=text, origin=claimed, label=path.name)
            if self.once:
                return
            time.sleep(self.poll_seconds)

    def _settled(self, path: Path) -> bool:
        """Still being copied in? Let it finish."""
        try:
            first = _footprint(path)
            time.sleep(self.settle_seconds)
            return first is not None and _footprint(path) == first
        except OSError:
            return False


def _footprint(path: Path) -> Optional[Tuple[int, int]]:
    """``(file count, total bytes)`` — a folder's own size says nothing about its contents."""
    if path.is_file():
        return 1, path.stat().st_size
    if path.is_dir():
        files = [p for p in path.rglob("*") if p.is_file()]
        return len(files), sum(p.stat().st_size for p in files)
    return None


__all__ = ["FolderWatchSource"]
