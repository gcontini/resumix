"""What is wrong with one CV: the content review and the page check together.

No model and no LaTeX — the reviewer is a :class:`FakeSelector` answering in
plain text, one violation per line, and the render is replaced by a fake that
lets a test choose how long the PDF came out.
"""

from __future__ import annotations

import pytest

from resumix_server.pipeline.cv_renderer import CVRenderer, RenderResult
from resumix_server.pipeline.cv_validator import MAX_VIOLATIONS, CVValidator

from server_helpers import FakeSelector, sample_cv_data

OK_REVIEW = ""                          # nothing to fix: an empty reply
REJECT = "invented a job at NASA"


@pytest.fixture
def renders(monkeypatch):
    """Count the renders and choose their length, without pdflatex."""
    state = {"pages": 1, "calls": 0, "stems": [], "document": None}

    def fake_render(self, document, *, stem="cv"):
        state["calls"] += 1
        state["stems"].append(stem)
        state["document"] = dict(document)
        pages = state["pages"]
        return RenderResult(
            tex="", pdf=b"%PDF", pages=pages,
            advice="length OK" if pages <= 2 else "REMOVE 1 duty.",
        )

    monkeypatch.setattr(CVRenderer, "render_document", fake_render)
    return state


def build(bundle, candidate, tmp_path, model) -> CVValidator:
    renderer = CVRenderer(
        template_source=bundle.template_source,
        template_name=bundle.template_name,
        work_dir=tmp_path,
    )
    return CVValidator(
        review_model=model,
        renderer=renderer,
        master_profile=candidate.profile,
        review_prompt=bundle.sys_prompt_review,
        # The ledger belongs to the caller; here it is one plain call.
        call=lambda selector, messages, response_format: selector.completions_create(
            messages, response_format=response_format
        ),
    )


def cv_and_document(candidate_data, **overrides):
    """What the model wrote, and the same CV with the real contact details on
    top — the reviewer gets the first, the renderer the second."""
    cv_data = sample_cv_data(**overrides)
    return cv_data, {**cv_data.model_dump(), **dict(candidate_data)}


def test_a_cv_that_reads_well_and_fits_has_nothing_wrong_with_it(
    bundle, candidate, candidate_data, tmp_path, renders
):
    model = FakeSelector(OK_REVIEW)
    cv_data, document = cv_and_document(candidate_data)

    result = build(bundle, candidate, tmp_path, model).validate(
        cv_data, document, attempt=0
    )

    assert result.violations == []
    assert result.pages == 1
    assert renders["stems"] == ["attempt_1"]


def test_a_cv_the_reviewer_rejected_is_rendered_anyway(
    bundle, candidate, candidate_data, tmp_path, renders
):
    """The whole point: the page count is measured even when the reviewer has
    already said no, so one round finds everything wrong with the CV."""
    model = FakeSelector(REJECT)
    cv_data, document = cv_and_document(candidate_data)

    result = build(bundle, candidate, tmp_path, model).validate(
        cv_data, document, attempt=0
    )

    assert result.violations == ["invented a job at NASA"]
    assert renders["calls"] == 1


def test_too_long_is_a_violation_in_the_condenser_s_own_words(
    bundle, candidate, candidate_data, tmp_path, renders
):
    renders["pages"] = 3
    model = FakeSelector(OK_REVIEW)
    cv_data, document = cv_and_document(candidate_data)

    result = build(bundle, candidate, tmp_path, model).validate(
        cv_data, document, attempt=0
    )

    assert result.violations == ["REMOVE 1 duty."]
    assert result.pages == 3


def test_the_length_complaint_comes_last(
    bundle, candidate, candidate_data, tmp_path, renders
):
    """Content first, length appended: the model is told what to say before it
    is told how much room it has to say it in."""
    renders["pages"] = 3
    model = FakeSelector(REJECT)
    cv_data, document = cv_and_document(candidate_data)

    result = build(bundle, candidate, tmp_path, model).validate(
        cv_data, document, attempt=0
    )

    assert result.violations == ["invented a job at NASA", "REMOVE 1 duty."]


def test_the_review_does_not_run_again_once_it_has_passed(
    bundle, candidate, candidate_data, tmp_path, renders
):
    """A CV shortened for length is the reviewed CV with less in it. Asking the
    most expensive call in the pipeline to re-confirm that buys nothing."""
    model = FakeSelector(OK_REVIEW)
    cv_data, document = cv_and_document(candidate_data)
    validator = build(bundle, candidate, tmp_path, model)

    validator.validate(cv_data, document, attempt=0)
    assert validator.content_reviewed

    renders["pages"] = 3
    result = validator.validate(cv_data, document, attempt=1)

    assert len(model.calls) == 1                      # no second review
    assert result.violations == ["REMOVE 1 duty."]
    assert renders["stems"] == ["attempt_1", "attempt_2"]


def test_a_rejection_leaves_the_review_running_next_round(
    bundle, candidate, candidate_data, tmp_path, renders
):
    model = FakeSelector(REJECT, OK_REVIEW)
    cv_data, document = cv_and_document(candidate_data)
    validator = build(bundle, candidate, tmp_path, model)

    validator.validate(cv_data, document, attempt=0)
    assert not validator.content_reviewed

    assert validator.validate(cv_data, document, attempt=1).violations == []
    assert validator.content_reviewed
    assert len(model.calls) == 2


def test_the_reviewer_is_never_shown_your_candidate_data(
    bundle, candidate, candidate_data, tmp_path, renders
):
    """Why validate() takes the CV twice: the reviewer sees what the model
    wrote, the renderer sees the merged document — or it measures a page count
    that is not the page count of the CV you will send."""
    model = FakeSelector(OK_REVIEW)
    cv_data, document = cv_and_document(candidate_data)

    build(bundle, candidate, tmp_path, model).validate(cv_data, document, attempt=0)

    assert candidate_data["email"] not in model.last_prompt
    assert renders["document"]["email"] == candidate_data["email"]


def test_each_line_is_one_violation_and_blank_or_short_lines_are_none(
    bundle, candidate, candidate_data, tmp_path, renders
):
    """A line too short to say where and what is not an instruction — which
    also disposes of a stray code fence or a bare "OK"."""
    model = FakeSelector(
        "Location: Summary. Offending quote: 'led'. FIX: say 'worked on'.\n"
        "\n"
        "```\n"
        "OK\n"
        "  Location: Skills. Offending quote: 'Rust'. FIX: remove it.  \n"
    )
    cv_data, document = cv_and_document(candidate_data)

    result = build(bundle, candidate, tmp_path, model).validate(
        cv_data, document, attempt=0
    )

    assert result.violations == [
        "Location: Summary. Offending quote: 'led'. FIX: say 'worked on'.",
        "Location: Skills. Offending quote: 'Rust'. FIX: remove it.",
    ]


@pytest.mark.parametrize("reply", ["OK", "ok", "Ok.", "  OK  "])
def test_a_bare_ok_is_an_approval_not_a_violation(
    bundle, candidate, candidate_data, tmp_path, renders, reply
):
    """The prompt asks for an empty reply, but a model that answers "OK"
    anyway has still approved the CV, not written a one-word violation."""
    model = FakeSelector(reply)
    cv_data, document = cv_and_document(candidate_data)

    result = build(bundle, candidate, tmp_path, model).validate(
        cv_data, document, attempt=0
    )

    assert result.violations == []


def test_a_review_longer_than_the_cap_keeps_the_most_important(
    bundle, candidate, candidate_data, tmp_path, renders
):
    """The prompt asks for the most important first, so the cap keeps the head:
    a runaway review must not bloat the next round's prompt."""
    lines = [f"Location: duty {n}. Offending quote: q. FIX: f." for n in range(1, 13)]
    model = FakeSelector("\n".join(lines))
    cv_data, document = cv_and_document(candidate_data)

    result = build(bundle, candidate, tmp_path, model).validate(
        cv_data, document, attempt=0
    )

    assert result.violations == lines[:MAX_VIOLATIONS]


def test_a_review_that_was_cut_off_is_asked_again_not_read_as_a_pass(
    bundle, candidate, candidate_data, tmp_path, renders
):
    """An empty reply is a pass, so a reply the token limit stopped short must
    not be mistaken for one: it is asked for again, and only after a second
    cut-off does the CV go through unreviewed, with a warning."""
    model = FakeSelector("Location: Summary. Offending quo", finish_reason="length")
    cv_data, document = cv_and_document(candidate_data)

    result = build(bundle, candidate, tmp_path, model).validate(
        cv_data, document, attempt=0
    )

    assert len(model.calls) == 2
    assert "cut off" in model.calls[1]["messages"][-1]["content"]
    assert result.violations == []          # the half-line never became a violation


def test_the_reviewer_is_asked_for_text_not_json(
    bundle, candidate, candidate_data, tmp_path, renders
):
    model = FakeSelector(OK_REVIEW, structured_output="json_schema_strict")
    cv_data, document = cv_and_document(candidate_data)

    build(bundle, candidate, tmp_path, model).validate(cv_data, document, attempt=0)

    assert "response_format" not in model.calls[0]
