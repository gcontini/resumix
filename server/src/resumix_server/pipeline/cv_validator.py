"""Judging the CV: everything wrong with one attempt, in one list.

Two things can be wrong with a tailored CV — it can say something the master
profile does not support, and it can run over the page limit — and they used
to be found in two different places, one round apart. They are found together
here, and come back as one list of violations written in the words the model
is about to be given: the reviewer's own complaints first, what to cut
appended last.

The render is unconditional. A ``pdflatex`` pass costs about a second and a
content review costs the most expensive call in the pipeline, so there is
nothing to save by withholding the page count from a CV the reviewer has
already rejected — and measuring it anyway means a CV that is both overstated
and too long is told about both in one round instead of two.

The review, by contrast, runs until it passes once. After that later rounds
only shorten a CV the reviewer has already accepted, and re-confirming that
would spend that same expensive call to hear the same answer.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Callable, List, Mapping

from ..model_selector import ModelSelector
from ..observability import LOGGER_ROOT, stage
from .cv_renderer import CVRenderer
from .cv_schema import TailoredCVData
from .parsing import raw_excerpt, reply_diagnostics

logger = logging.getLogger(f"{LOGGER_ROOT}.cv")

#: The most complaints one review can hand back. The prompt asks for at most
#: this many, most important first; this is the backstop when a model writes
#: more, so a runaway review cannot bloat the next round's prompt.
MAX_VIOLATIONS = 10

#: One counted model call, ``(model, messages, response_format)``. The ledger
#: belongs to the caller, so the review's tokens are added to the same total
#: the progress lines report.
CallFn = Callable[..., Any]


@dataclass(frozen=True)
class ValidationResult:
    """What is wrong with one CV, and how long it came out.

    An empty ``violations`` is the CV passing; there is no separate verdict
    that could disagree with the list. When it is not empty, every entry is an
    instruction the model can act on, and the length complaint — when there is
    one — is the last of them.
    """

    violations: List[str]
    pages: int


class CVValidator:
    """Says what is wrong with one CV: its content, then its length."""

    def __init__(
        self,
        *,
        review_model: ModelSelector,
        renderer: CVRenderer,
        master_profile: Mapping[str, Any],
        review_prompt: str,
        call: CallFn,
    ) -> None:
        self.review_model = review_model
        self.renderer = renderer
        self._master_profile = dict(master_profile)
        self._review_message = {"role": "system", "content": review_prompt}
        self._call = call
        #: True once the content review has passed. Public because the caller
        #: names the step it is about to run from it.
        self.content_reviewed = False

    # --- public API ---------------------------------------------------------
    def validate(
        self, cv_data: TailoredCVData, document: Mapping[str, Any], *, attempt: int
    ) -> ValidationResult:
        """Review the content, render it, measure it, and report everything wrong.

        Both halves of the same CV are passed in because they have different
        audiences: the reviewer is shown ``cv_data`` and never the candidate's
        own details, while the renderer needs ``document`` — the merged one —
        or it measures a page count that is not the page count of the CV you
        will send.

        The render happens whatever the review said. It is cheap, and the model
        can only fix what it is told about in the round it is told.
        """
        violations: List[str] = []

        if not self.content_reviewed:
            logger.info("--- content review ---")
            with stage("cv.review"):
                violations = self._review_cv_data(cv_data, attempt)
            if violations:
                logger.info(
                    "  ✗ Review rejected CV (%d violation(s))", len(violations)
                )
                for violation in violations:
                    logger.info("      - %s", violation)
            else:
                logger.info("  ✓ Review OK")
                self.content_reviewed = True

        logger.info("--- render %d ---", attempt + 1)
        with stage("render"):
            result = self.renderer.render_document(
                document, stem=f"attempt_{attempt + 1}"
            )
        logger.info("  Page check: %d pages -> %s", result.pages, result.advice)

        if result.pages > self.renderer.page_limit:
            # result.advice is already written as an instruction: it is handed
            # to the model verbatim, as the last thing it has to fix.
            violations.append(result.advice)
        else:
            logger.info("  ✓ Length OK (%d pages)", result.pages)

        return ValidationResult(violations=violations, pages=result.pages)

    # --- the content review -------------------------------------------------
    @staticmethod
    def _violations_from(response) -> List[str]:
        """The reviewer's complaints: one per line of its plain-text reply.

        An empty reply is a pass, and so is a bare "OK" — asked for nothing
        when the CV is acceptable, the model sometimes writes that single word
        anyway, and it is an approval, not a one-word violation. A reply the
        token limit cut off is neither: it stopped before it could say what it
        found, so it raises ``ValueError`` and is asked again rather than read
        as nothing to fix. A line too short to say where and what is dropped,
        which also disposes of a stray code fence.
        """
        choice = response.choices[0]
        if choice.finish_reason == "length":
            raise ValueError("the review was cut off before it finished")
        content = (choice.message.content or "").strip()
        if content.rstrip(".").upper() == "OK":
            return []
        lines = (line.strip() for line in content.splitlines())
        return [line for line in lines if len(line) > 15][:MAX_VIOLATIONS]

    def _review_cv_data(self, cv_data: TailoredCVData, attempt: int) -> List[str]:
        """Review generated CV content against the master profile.

        Uses ``review_model`` with the review system prompt; the master profile
        and the generated CV are the only inputs, and the reply is plain text,
        one violation per line. Its sampling is its own role's business —
        ``models.toml`` ships it at ``temperature = 0``, because a reviewer
        that samples draws a different set of violations every round and the
        loop has no fixed point to settle on.
        A reply that was cut off is asked for once more; if the second one is
        cut off too a warning is printed and no violations are returned, so the
        unvalidated CV proceeds through the pipeline.
        """

        review_request = ("Review the GENERATED CV below against the candidate MASTER "
            "PROFILE.\n")
        if attempt > 0:
            review_request += ("The GENERATED CV has already been reviewed "+str(attempt +1)+
                               " times, it should be ok by now. "
            "Flag only outstanding syntax and logic issues this turn, if there are any.")
        review_request += (
            "--------------------------------------------\n"
            "MASTER PROFILE:\n"
            f"{json.dumps(self._master_profile, indent=2)}\n"
            "--------------------------------------------\n"
            "GENERATED CV:\n"
            f"{cv_data.model_dump_json(indent=2)}\n"
            "--------------------------------------------\n"
            "Reply with the violations, one per line and nothing else — an "
            "empty reply if the CV is acceptable."
        )

        messages = [
            self._review_message,
            {"role": "user", "content": review_request},
        ]

        for retry in range(2):
            # No response_format: the reply is text, and a JSON mode would
            # only ask the model for a shape nobody parses.
            resp = self._call(self.review_model, messages, None)

            messages.append(
                {"role": "assistant", "content": resp.choices[0].message.content}
            )

            try:
                return self._violations_from(resp)
            except ValueError as e:
                logger.error(
                    "  ✗ Review response unusable (retry %d): %s: %s\n"
                    "    reply: %s\n"
                    "    payload: %s",
                    retry + 1, type(e).__name__, e,
                    reply_diagnostics(resp),
                    raw_excerpt(resp.choices[0].message.content),
                )
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Your previous reply was cut off before it "
                            "finished. Reply again: the violations, one per "
                            "line, nothing else."
                        ),
                    }
                )

        # After 2 failed attempts do not block the job: warn and let the
        # (unvalidated) CV proceed as if the review passed.
        logger.warning(
            "  ⚠ Content reviewer failed to finish a review in 2 attempts "
            "— continuing with the unvalidated CV"
        )
        return []


__all__ = ["CVValidator", "ValidationResult"]
