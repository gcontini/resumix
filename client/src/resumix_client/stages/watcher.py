"""The four stages at once.

Recovery first, synchronously: whatever an earlier run left in ``working/``
is sent on before anything new is read. Then the inbox and the CV writer run
on threads of their own, and the approval loop runs here, on the main thread,
so Ctrl-C lands where it can stop everything.

``q`` stops gently: nothing new is queued, the inbox finishes the posting in
hand, the CV writer finishes the generation in hand, and both are waited for.
Ctrl-C is not handled here at all. It propagates, the threads (daemons) go
with the process, and the next start picks up whatever they were doing.
"""

from __future__ import annotations

import threading
import traceback
from typing import Callable, List

from .approval import HumanApproval
from .generation import GenerationWorker
from .inbox import InputProcessor
from .terminal import Console, Keyboard
from .working import WorkingProcessor


class Watcher:
    """Starts the stages, and stops them when you quit."""

    def __init__(
        self,
        working: WorkingProcessor,
        inbox: InputProcessor,
        generation: GenerationWorker,
        approval: HumanApproval,
        keyboard: Keyboard,
        console: Console,
        *,
        join_seconds: float = 0.5,
    ) -> None:
        self.working = working
        self.inbox = inbox
        self.generation = generation
        self.approval = approval
        self.keyboard = keyboard
        self.console = console
        self.join_seconds = join_seconds
        self._crashed = False

    def run(self) -> int:
        """Until you quit. 1 if a job failed or a stage crashed, else 0."""
        self.working.recover()
        stop = threading.Event()
        self.keyboard.start()
        threads = [
            self._start("inbox", self.inbox.run, stop),
            self._start("cv", self.generation.run, stop),
        ]
        self.approval.run(stop)

        self.working.close()
        stop.set()
        self._wait(threads)
        left = [p for p in self.working.workspace.working.iterdir() if not p.name.startswith(".")]
        if left:
            self.console.say(f"⏹ stopped. {len(left)} posting(s) wait in working/ "
                             "for the next start.")
        else:
            self.console.say("⏹ stopped.")
        return 1 if self.working.failures or self._crashed else 0

    def _start(
        self, name: str, target: Callable[[threading.Event], None], stop: threading.Event
    ) -> threading.Thread:
        """A stage on a daemon thread. A crash stops every stage, loudly."""

        def guarded() -> None:
            try:
                target(stop)
            except Exception:
                self._crashed = True
                self.console.say(f"✗ the {name} thread stopped:\n"
                                 f"{traceback.format_exc().rstrip()}")
                stop.set()

        thread = threading.Thread(target=guarded, name=name, daemon=True)
        thread.start()
        return thread

    def _wait(self, threads: List[threading.Thread]) -> None:
        """Join in short steps: a lock wait cannot be interrupted on Windows,
        and Ctrl-C has to stay a way out while the last CV is finished."""
        busy = [
            f"the analysis of {self.inbox.current}" if self.inbox.current else "",
            f"the generation of {self.generation.current}" if self.generation.current else "",
        ]
        busy = [what for what in busy if what]
        if busy:
            self.console.say(f"⏳ finishing {' and '.join(busy)}. Ctrl-C to stop now.")
        while any(thread.is_alive() for thread in threads):
            for thread in threads:
                thread.join(timeout=self.join_seconds)


__all__ = ["Watcher"]
