"""One server call, and the server's own account of it when that is worth having.

On failure always; on every call with ``--debug``. Both the inbox and the CV
writer call the server, and "fetch the log too" is one decision in one place.
"""

from __future__ import annotations

from typing import Callable, Optional, TypeVar

from resumix_contracts import Envelope

from ..api import ResumixApi, ResumixError
from ..joblog import JobLog

T = TypeVar("T")


class Calls:
    """The API, plus what its log policy needs."""

    def __init__(self, api: ResumixApi, *, debug: bool = False) -> None:
        self.api = api
        self.debug = debug

    def make(self, log: JobLog, call: Callable[[], Envelope[T]]) -> T:
        """Make one call; with ``--debug``, keep what the server said about it."""
        envelope = call()
        if self.debug:
            self.fetch_log(log, envelope.request_id)
        return envelope.data

    def fetch_log(self, log: JobLog, request_id: Optional[str]) -> None:
        """Fold one request's server-side log into the job's ``log.log``."""
        if not request_id:
            return
        try:
            log.server(request_id, self.api.logs(request_id).data.entries)
        except ResumixError as exc:
            log.step(f"⚠ could not fetch the server log for {request_id}: {exc}")

    def failed(self, log: JobLog, exc: ResumixError) -> None:
        """A call failed: say so, and keep the server's account of it."""
        log.step(f"✗ {exc}")
        if exc.request_id:
            log.step(f"   request id: {exc.request_id}")
        self.fetch_log(log, exc.request_id)


__all__ = ["Calls"]
