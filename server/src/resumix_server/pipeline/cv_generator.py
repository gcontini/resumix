"""Writing the CV: job description in, :class:`TailoredCVData` out.

The loop is generate -> validate -> regenerate: every round writes a CV,
:class:`~resumix_server.pipeline.cv_validator.CVValidator` says what is wrong
with it, and what it says becomes the next round's task. The render inside
that check is the point: the two-page limit is measured on a real compiled
PDF, so the instruction fed back to the model ("remove 1 duty") is grounded in
what actually overflowed rather than a guess. The PDFs produced along the way
are thrown out with the scratch directory; after the last round the keywords
are highlighted and the result is rendered once more, for good.

The page checks render your ``candidate_data`` too. They have to: a page
count taken with the contact details missing is not the page count of the CV
you will send. No model is shown that data — it goes to the template and
nowhere else — but the renderer needs it, and so the endpoint takes it.

Every input arrives in memory — prompts and template in a
:class:`~resumix_server.bundle.ResourceBundle`, the profile and the
candidate data in :class:`~resumix_server.bundle.CandidateInputs`. Nothing
is read from disk and nothing is written outside ``work_dir``.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from pydantic import ValidationError

from ..bundle import CandidateInputs, ResourceBundle
from ..model_selector import ModelSelector
from ..observability import LOGGER_ROOT, stage
from .cv_renderer import CVRenderer
from .cv_schema import TailoredCVData, prompt_schema
from .cv_validator import CVValidator
from .errors import BudgetExceededError, ModelOutputError
from .parsing import parse_model_json, raw_excerpt, reply_diagnostics

logger = logging.getLogger(f"{LOGGER_ROOT}.cv")


def _retry_prompt(cv_data: TailoredCVData, violations: List[str]) -> str:
    """The CV to improve on, and everything to fix in it, for the next round.

    A rejected CV comes back as material in a fresh prompt rather than as the
    model's own previous turn: told to fix its own reply, the model copy-edits
    it — carrying over whatever was wrong with it — instead of writing a CV.

    One list, whatever the complaints are about. An overstatement and an
    overflowing page are the same kind of instruction to the model, and it can
    only fix the ones it is shown in the round it is shown them.
    """
    return (
        "\n--------------------------------------------\n"
        "YOUR PREVIOUS ATTEMPT, rejected:\n"
        f"{cv_data.model_dump_json(indent=2)}\n"
        "--------------------------------------------\n"
        "* Output a single valid JSON object strictly matching the TailoredCVData schema. \n"
        "* **Keep** the former field values from 'YOUR PREVIOUS ATTEMPT', copy them 'as is'"
        " EXCEPT where a violation below requires a change.\n"
        "* **Fix** ALL of the violations below:\n"
        + "\n".join(f"- {v}" for v in violations)
    )


#: Called as the run moves on: the step starting now, and one line about the
#: one that just finished. Both go straight to a client, unread by anything.
ProgressFn = Callable[[str, str], None]


class CVGenerator:
    """Generates tailored CV content for one job description.

    Parameters
    ----------
    cv_model:
        The ``cv`` model: writes the CV. Built once by the caller and shared
        across requests — it holds an HTTP client, not per-job state.
    review_model:
        The ``review`` model: judges each CV against the master profile and
        answers in plain text, one violation per line. Shared the same way.
    highlight_model:
        The ``highlight`` model, which adds ``**bold**``/``*italics*`` markers
        to the finished content. ``None`` skips that pass.
    bundle:
        Prompts and the LaTeX template for this run (defaults, or whatever the
        request overrode).
    candidate:
        The profile the model tailors from. Not cached; it dies with the
        request.
    work_dir:
        Scratch directory for the page-check renders. Created and removed by
        the caller.
    max_attempts:
        Generate -> validate rounds before giving up and delivering the last
        CV anyway.
    max_validation_attempts:
        Schema-validation retries within one round.
    deadline:
        Optional :func:`time.monotonic` value. Checked between rounds so a run
        that cannot finish in time fails with a clear cause instead of being
        cut off by a proxy.
    progress:
        Called at each step boundary. ``None`` runs the whole thing silently,
        which is what every test does.
    """

    def __init__(
        self,
        *,
        cv_model: ModelSelector,
        review_model: ModelSelector,
        bundle: ResourceBundle,
        candidate: CandidateInputs,
        work_dir: Path,
        highlight_model: Optional[ModelSelector] = None,
        max_attempts: int = 4,
        max_validation_attempts: int = 3,
        deadline: Optional[float] = None,
        latex_timeout: Optional[float] = None,
        page_limit: Optional[int] = None,
        progress: Optional[ProgressFn] = None,
    ) -> None:
        self.cv_model = cv_model
        self.highlight_model = highlight_model
        self.bundle = bundle
        self.candidate = candidate
        self.work_dir = Path(work_dir)
        self.max_attempts = max_attempts
        self.max_validation_attempts = max_validation_attempts
        self.deadline = deadline
        self.progress = progress
        self._calls = 0
        self._tokens = 0
        self._thinking = 0

        renderer_kwargs: Dict[str, Any] = {}
        if latex_timeout is not None:
            renderer_kwargs["latex_timeout"] = latex_timeout
        if page_limit is not None:
            renderer_kwargs["page_limit"] = page_limit
        self.renderer = CVRenderer(
            template_source=bundle.template_source,
            template_name=bundle.template_name,
            assets=bundle.assets,
            work_dir=self.work_dir,
            **renderer_kwargs,
        )

        self._master_profile = dict(candidate.profile)
        self._system_message = {"role": "system", "content": bundle.sys_prompt_cv}
        self._highlight_message = {"role": "system", "content": bundle.sys_prompt_highlight}
        self._cached_schema = prompt_schema()

        # What is wrong with a CV is its own question, asked by its own class.
        # It is handed this generator's counted call, so a review's tokens land
        # on the one ledger the progress lines are costed from.
        self.validator = CVValidator(
            review_model=review_model,
            renderer=self.renderer,
            master_profile=self._master_profile,
            review_prompt=bundle.sys_prompt_review,
            call=self._call,
        )

    # --- helpers ------------------------------------------------------------
    def _call(self, model: ModelSelector, messages, response_format):
        """Every model call goes through here, so a step can be costed.

        The per-call line in the log is still the ledger. The counters are the
        same numbers added up, so a step can say what it cost while it is still
        running; a call that reports no usage adds nothing.
        """
        response = model.completions_create(messages, response_format=response_format)
        self._calls += 1
        usage = getattr(response, "usage", None)
        if usage is not None:
            details = getattr(usage, "completion_tokens_details", None)
            self._tokens += (getattr(usage, "prompt_tokens", 0) or 0) + (
                getattr(usage, "completion_tokens", 0) or 0
            )
            self._thinking += getattr(details, "reasoning_tokens", 0) or 0
        return response

    def _mark(self) -> Tuple[int, int, float]:
        """Where the counters stand now; a step's cost is the difference."""
        return self._tokens, self._thinking, time.monotonic()

    def _cost(self, mark: Tuple[int, int, float], what: str) -> str:
        tokens, thinking, started = mark
        return (
            f"{what}, tokens used={self._tokens - tokens}, "
            f"thinking={self._thinking - thinking}, "
            f"elapsed={time.monotonic() - started:.1f}s"
        )

    def _report(self, status: str, detail: str = "") -> None:
        if self.progress is not None:
            self.progress(status, detail)

    def _document(self, cv_data: TailoredCVData) -> Dict[str, Any]:
        """One flat namespace for the template.

        Your own data goes over the top, so a field the model invents can
        never replace a real name, email or address.
        """
        return {**cv_data.model_dump(), **dict(self.candidate.data)}

    def _highlight_keywords(
        self, cv_data: TailoredCVData, job_description: str
    ) -> TailoredCVData:
        """Add ``**bold**``/``*italics*`` keyword markers to validated CV data.

        Uses the separate ``highlight_model`` (when configured) on the
        already schema-validated ``cv_data``. The highlighter only inserts
        Markdown markers inside existing string values — content, structure
        and order are preserved — following the rules in the highlight prompt.
        The ``response_format`` is whatever the highlighter's endpoint
        declares it supports (see
        :meth:`~resumix.model_selector.ModelSelector.response_format`); the
        ``TailoredCVData`` JSON schema is also restated in the prompt, which
        substitutes for the structural guarantee strict ``json_schema`` mode
        would otherwise give on endpoints that lack it.
        Up to 2 attempts: on any failure (empty/invalid output) a warning
        (including ``finish_reason`` and any reasoning-token usage, for
        diagnosing truncation) is printed and, after the last attempt, the
        un-highlighted ``cv_data`` is returned so the job still succeeds.
        Returns the highlighted data re-validated as :class:`TailoredCVData`.
        """
        if self.highlight_model is None:
            return cv_data

        messages = [
            self._highlight_message,
            {
                "role": "user",
                "content": (
                    "Highlight the keywords in the CV_DATA below.\n"
                    "Output the SAME JSON object (CV_DATA), unchanged except for the "
                    "added **bold**/*italics* markers inside string values. The "
                    "output MUST be a single JSON object valid against this JSON "
                    "Schema:\n"
                    "--------------------------------------------\n"
                    "JSON_SCHEMA:\n"
                    f"{json.dumps(self._cached_schema)}\n"
                    "--------------------------------------------\n"
                    "CV_DATA:\n"
                    f"{cv_data.model_dump_json(indent=2)}\n"
                    "--------------------------------------------\n"
                    "JOB_DESCRIPTION:\n"
                    f"{job_description}\n"
                    "--------------------------------------------\n"
                ),
            },
        ]

        max_attempts = 2
        for attempt in range(max_attempts):
            resp = self._call(
                self.highlight_model,
                messages,
                self.highlight_model.response_format("cv_data", self._cached_schema),
            )
            try:
                return parse_model_json(resp.choices[0].message.content, TailoredCVData)
            except (ValueError, ValidationError) as e:
                diag = reply_diagnostics(resp)
                if attempt + 1 < max_attempts:
                    logger.warning(
                        "  ↻ highlighting attempt %d failed (%s: %s; %s) — retrying",
                        attempt + 1, type(e).__name__, e, diag,
                    )
                    continue
                logger.warning(
                    "  ⚠ highlighting failed (%s: %s; %s) — continuing with the "
                    "un-highlighted CV\n    payload: %s",
                    type(e).__name__, e, diag,
                    raw_excerpt(resp.choices[0].message.content),
                )
                return cv_data

        return cv_data  # unreachable: loop always returns on its last iteration

    def _generate_valid_cv_data(self, prompt: str) -> TailoredCVData:
        """Generate and schema-validate :class:`TailoredCVData` for one prompt.

        Runs up to ``max_validation_attempts`` calls against ``cv_model``
        (json_schema ``response_format``), feeding the validation errors back
        to the LLM until the output is valid. Raises ``ModelOutputError`` when
        no valid payload is produced.

        The conversation is built here and dropped on return, so only the
        schema-correction turns ever accumulate — one round's CV never becomes
        context for the next.
        """
        messages: List[Dict[str, Any]] = [
            self._system_message,
            {"role": "user", "content": prompt},
        ]
        for val_attempt in range(self.max_validation_attempts):
            cv = self._call(
                self.cv_model,
                messages,
                self.cv_model.response_format("cv_data", self._cached_schema),
            )

            messages.append(
                {"role": "assistant", "content": cv.choices[0].message.content}
            )

            try:
                cv_data = parse_model_json(cv.choices[0].message.content, TailoredCVData)
                # The payload is logged on the way through, not only when it
                # is rejected: a CV can be schema-valid and still garbled, and
                # then this is the only record of what the model actually wrote.
                logger.info(
                    "  ✓ Output validated against TailoredCVData "
                    "(validation attempt %d)\n    payload: %s",
                    val_attempt + 1, raw_excerpt(cv.choices[0].message.content),
                )
                return cv_data
            except (ValueError, ValidationError) as e:
                logger.error(
                    "  ✗ Validation failed (attempt %d): %s: %s\n"
                    "    reply: %s\n"
                    "    payload: %s",
                    val_attempt + 1, type(e).__name__, e,
                    reply_diagnostics(cv),
                    raw_excerpt(cv.choices[0].message.content),
                )
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Your previous response was NOT valid against the "
                            "TailoredCVData schema.\n"
                            f"Validation error: {type(e).__name__}: {e}\n\n"
                            "Fix the errors above and output a single valid JSON "
                            "object strictly matching the TailoredCVData schema."
                        ),
                    }
                )

        raise ModelOutputError(
            "Could not obtain valid TailoredCVData after "
            f"{self.max_validation_attempts} validation attempts.",
            stage="cv.generate",
        )

    def generate(
        self, job_description: str
    ) -> Tuple[Dict[str, Any], str, bytes, str]:
        """Write, check, condense, highlight and render one CV.

        Each round writes a CV and hands it to the validator, which reviews
        the content against the profile, renders it and measures it; whatever
        it finds wrong comes back as one list and becomes the next round's
        task. Running out of rounds is not a failure — the last CV is
        delivered and the log says what is still open, because a CV one line
        too long is worth more to the caller than an error. After the loop the
        keywords are highlighted once and the result is rendered for good.

        Returns the merged document, its LaTeX, its PDF and one line saying
        what the run cost.
        """
        started = time.monotonic()
        user_prompt = (
            "Please tailor my CV for this JOB DESCRIPTION. "
            "Output strictly json format.\n"
            "--------------------------------------------\n"
            "MASTER PROFILE:\n"
            f"{json.dumps(self._master_profile, indent=2)}\n"
            "--------------------------------------------\n"
            "JOB DESCRIPTION:\n"
            f"{job_description}\n\n"
        )
        if not self.cv_model.sends_schema():
            user_prompt += (
                "--------------------------------------------\n"
                "JSON_SCHEMA (TailoredCVData) the output must satisfy:\n"
                f"{json.dumps(self._cached_schema)}\n"
            )

        final_cv_data = None
        # What the last round got wrong, appended to the task prompt for the
        # next one. Every attempt is its own conversation: the attempts used
        # to accumulate, and a model shown three of its own near-identical
        # replies stops writing and starts copying them.
        retry = ""
        # Each report names the step starting now and what the one before it
        # cost, so one call is one complete answer to "where is my CV".
        self._report("generate")

        for attempt in range(self.max_attempts):
            # Stop before starting a round that cannot finish in the budget.
            if self.deadline is not None and time.monotonic() >= self.deadline:
                raise BudgetExceededError(
                    f"time budget exhausted after {attempt} attempt(s)",
                    stage="cv.generate",
                    detail={"attempts": attempt},
                )
            logger.info("--- attempt %d ---", attempt + 1)

            # Generate -> validate against TailoredCVData, feeding the
            # validation errors back to the LLM until the output is
            # schema-valid.
            mark = self._mark()
            with stage("cv.generate"):
                cv_data = self._generate_valid_cv_data(user_prompt + retry)
            # The content review is the long half of the check and runs only
            # until it passes; after that the step is named for the render.
            self._report(
                "review" if not self.validator.content_reviewed else "page_check",
                self._cost(mark, "generation finished"),
            )

            # Review, render, measure. Every attempt is rendered, rejected or
            # not, so there is always a CV to fall back on and both kinds of
            # complaint are found in the same round.
            mark = self._mark()
            result = self.validator.validate(
                cv_data, self._document(cv_data), attempt=attempt
            )
            final_cv_data = cv_data

            if not result.violations:
                self._report(
                    "highlight",
                    self._cost(mark, f"page check passed: {result.pages} page(s)"),
                )
                break

            if attempt + 1 >= self.max_attempts:
                # Out of attempts: deliver what the last round produced rather
                # than fail a job that has a usable CV in hand. What is still
                # wrong with it is on the record.
                logger.warning(
                    "  ⚠ %d violation(s) still open after %d attempt(s) — "
                    "delivering the last CV",
                    len(result.violations), self.max_attempts,
                )
                for violation in result.violations:
                    logger.info("      - %s", violation)
                # Still report the step: a client polling for "highlight"
                # should not have to tell giving up apart from succeeding.
                self._report(
                    "highlight",
                    self._cost(
                        mark,
                        f"out of attempts with {len(result.violations)} "
                        f"violation(s) open, {result.pages} page(s)",
                    ),
                )
                break

            logger.info("CV rejected — regenerating...")
            # The violations are the instruction, verbatim: the client sees the
            # same words the model is about to be given.
            violations_text = "\n".join(f"- {v}" for v in result.violations)
            self._report(
                "re-generate",
                self._cost(
                    mark,
                    f"CV rejected: {len(result.violations)} violation(s), "
                    f"{result.pages} page(s)",
                )
                + "\n"
                + violations_text,
            )
            retry = _retry_prompt(cv_data, result.violations)

        if final_cv_data is None:
            # Only reachable with max_attempts <= 0: every round that runs
            # keeps its CV.
            raise ModelOutputError(
                f"No CV was produced in {self.max_attempts} attempts.",
                stage="cv.generate",
                detail={"attempts": self.max_attempts},
            )

        # Keyword highlighting with the separate fast model — run ONCE, after
        # the loop, on the final (within page-limit) CV data (no retry loop —
        # the data is already schema-valid).
        logger.info("--- keyword highlighting ---")
        with stage("cv.highlight"):
            final_cv_data = self._highlight_keywords(final_cv_data, job_description)

        # The deliverable: the same render the page check did, on the
        # highlighted content, kept this time.
        document = self._document(final_cv_data)
        with stage("render"):
            result = self.renderer.render_document(document, stem="cv")
        summary = (
            f"done, {self._calls} model calls, tokens used={self._tokens}, "
            f"thinking={self._thinking}, "
            f"elapsed={time.monotonic() - started:.1f}s, {result.pages} page(s)"
        )
        return document, result.tex, result.pdf, summary


__all__ = ["CVGenerator"]
