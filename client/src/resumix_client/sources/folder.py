"""A dropped or named file, read as a posting.

The folder watcher that used to live here is now :mod:`resumix_client.stages`;
what is left is how ``submit`` and the recovery prompt read a file.
"""

from __future__ import annotations

from pathlib import Path


def read_text(path: Path) -> str:
    """Read whatever is there. Binary payloads are rejected downstream, so
    they must survive the read rather than raise."""
    return path.read_bytes().decode("utf-8", errors="replace")


__all__ = ["read_text"]
