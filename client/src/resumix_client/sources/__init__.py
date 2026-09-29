"""Where job descriptions come from.

``clipboard`` and ``submit`` differ in exactly one thing: what hands them the
next posting. That difference lives here, behind :class:`JDSource`, so they
share one pipeline instead of two copies of it. ``watch`` has its own staged
flow in :mod:`resumix_client.stages`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional, Protocol


@dataclass(frozen=True)
class JDCandidate:
    """One thing that might be a job description.

    ``origin`` is the file it arrived as, already claimed into ``working/``
    when there is one; the clipboard has none. Either way the job folder
    holds it as :data:`~resumix_client.workspace.JD_FILENAME`.

    ``origin`` may also be a claimed *folder* — an already-analysed job
    holding ``jd.txt`` and ``analysis.json`` — in which case ``text`` is empty.
    """

    text: str
    origin: Optional[Path] = None
    label: str = "clipboard"

    @property
    def is_job_folder(self) -> bool:
        return self.origin is not None and self.origin.is_dir()


class JDSource(Protocol):
    """Yields candidates until it has no more (or forever, for a watcher)."""

    def candidates(self) -> Iterator[JDCandidate]: ...


__all__ = ["JDCandidate", "JDSource"]
