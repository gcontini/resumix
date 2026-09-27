"""One named file as a source — ``resumix submit``."""

from __future__ import annotations

from pathlib import Path
from typing import Iterator, Optional

from . import JDCandidate
from .folder import read_text
from ..workspace import Workspace


class SingleFileSource:
    """Yields exactly one candidate: the file you named.

    It is *copied* into ``working/``, so it follows exactly the same path as a
    watched file — same trail on failure, same folder on success — while the
    file you pointed at stays where you left it. A watched folder is an inbox
    and gets emptied; an argument is not.

    With an ``analysis`` beside it, both are copied into a job folder instead,
    exactly like an analysed folder dropped into a watched inbox: detection
    and analysis are skipped.
    """

    def __init__(
        self, path: Path, workspace: Workspace, analysis: Optional[Path] = None
    ) -> None:
        self.path = Path(path)
        self.workspace = workspace
        self.analysis = Path(analysis) if analysis is not None else None

    def candidates(self) -> Iterator[JDCandidate]:
        for path in (self.path, self.analysis):
            if path is not None and not path.is_file():
                raise FileNotFoundError(f"no such file: {path}")
        if self.analysis is not None:
            folder = self.workspace.take_in_job(self.path, self.analysis)
            yield JDCandidate(text="", origin=folder, label=self.path.name)
            return
        claimed = self.workspace.take_in(self.path, move=False)
        yield JDCandidate(text=read_text(claimed), origin=claimed, label=self.path.name)


__all__ = ["SingleFileSource"]
