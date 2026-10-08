"""Stage 3: a CV written, filed and recorded — or failed and kept."""

from __future__ import annotations

import json
from dataclasses import replace

import openpyxl
import pytest
from resumix_contracts import CVStatus

from resumix_client.api import ResumixError
from resumix_client.stages.calls import Calls
from resumix_client.stages.generation import CvWriter, GenerationWorker
from resumix_client.stages.terminal import TaggedLog
from resumix_client.stages.working import WorkingProcessor
from resumix_client.tracking import build_tracker
from resumix_client.workspace import day

from conftest import JD_TEXT, FakeApi, analysis


def yes_posting(processor):
    folder = processor.submit(JD_TEXT, analysis(should_apply="YES"),
                              TaggedLog(processor.console, "posting.txt"))
    assert processor.generations.get_nowait() == folder
    return folder


def run_one(processor, writer, folder):
    GenerationWorker(processor, writer, processor.console).process(folder)


def row(workspace):
    sheet = openpyxl.load_workbook(workspace.root / "applications.xlsx").active
    headers = [c.value for c in sheet[1]]
    return dict(zip(headers, [c.value for c in sheet[2]]))


def test_a_cv_is_delivered_with_everything_needed_to_render_it_again(
        processor, writer, workspace, api):
    folder = yes_posting(processor)
    run_one(processor, writer, folder)

    delivered = workspace.cv / day() / "Acme_Corp_Head_of_IT"
    assert sorted(p.name for p in delivered.iterdir()) == [
        "analysis.json", "candidate_signature.png", "cv_jordan_rivera_head_of_it.json",
        "cv_jordan_rivera_head_of_it.pdf", "cv_jordan_rivera_head_of_it.tex", "jd.txt", "log.log",
    ]
    assert not folder.exists()
    assert api.calls == ["create_cv", "cv_status", "cv_result"]
    assert "writing the CV" in (delivered / "log.log").read_text()


def test_a_generated_cv_gets_a_spreadsheet_row_pointing_at_its_pdf(processor, writer, workspace):
    run_one(processor, writer, yes_posting(processor))

    recorded = row(workspace)
    assert (recorded["company_name"], recorded["job_title"]) == ("Acme Corp", "Head of IT")
    assert recorded["cv_path"] == str(workspace.cv / day() / "Acme_Corp_Head_of_IT"
                                      / "cv_jordan_rivera_head_of_it.pdf")


@pytest.mark.parametrize(
    "mode, expected, letter",
    [
        ("no", ["create_cv", "cv_status", "cv_result"], False),
        ("yes", ["create_cv", "cv_status", "cv_result", "letter"], True),
        ("letter_only", ["letter"], True),
    ],
)
def test_cover_letter_modes_decide_what_runs(api, config, workspace, console, mode, expected,
                                             letter):
    writer = CvWriter(Calls(api), replace(config, cover_letter=mode))
    processor = WorkingProcessor(workspace, writer, build_tracker(workspace.root, True), console)
    run_one(processor, writer, yes_posting(processor))

    delivered = workspace.cv / day() / "Acme_Corp_Head_of_IT"
    assert api.calls == expected
    assert (delivered / "cover_letter.txt").is_file() is letter
    assert (delivered / "cv_jordan_rivera_head_of_it.pdf").is_file() is (mode != "letter_only")
    cv_path = row(workspace)["cv_path"]
    if mode == "letter_only":
        assert cv_path is None
    else:
        assert cv_path.endswith("cv_jordan_rivera_head_of_it.pdf")


def test_the_temperature_goes_to_the_cv_and_the_letter(api, config, workspace, console):
    # FakeApi.analyze takes no temperature, so sending one to it would raise.
    writer = CvWriter(Calls(api), replace(config, cover_letter="yes", temperature=0.7))
    processor = WorkingProcessor(workspace, writer, build_tracker(workspace.root, True), console)
    run_one(processor, writer, yes_posting(processor))

    assert api.seen_temperature == 0.7
    assert api.seen_letter_temperature == 0.7


def test_a_failure_keeps_every_file_under_error_with_the_server_log(
        processor, writer, workspace, api):
    api.fail_on = "create_cv"
    folder = processor.submit(JD_TEXT, analysis(should_apply="CHECK"),
                              TaggedLog(processor.console, "posting.txt"))
    processor.approvals.get_nowait()
    processor.approve(folder)

    run_one(processor, writer, processor.generations.get_nowait())

    [failed] = workspace.error.glob("*/*_Acme_Corp_Head_of_IT")
    assert failed.parent.name == day()
    assert sorted(p.name for p in failed.iterdir()) == [
        "analysis.json", "approval_status.txt", "jd.txt", "log.log"]
    log = (failed / "log.log").read_text()
    assert "create_cv failed" in log
    assert "--- server request failed-request (1 line(s)) ---" in log
    assert api.calls.count("logs") == 1, "only the failed request, and without --debug"
    assert processor.failures == 1
    assert not (workspace.root / "applications.xlsx").exists()


def test_an_unfetchable_server_log_does_not_mask_the_failure(config, workspace, console):
    class Stubborn(FakeApi):
        def logs(self, request_id):
            raise ResumixError("unknown_request: logs are gone", status=404)

    writer = CvWriter(Calls(Stubborn(fail_on="create_cv")), config)
    processor = WorkingProcessor(workspace, writer, build_tracker(workspace.root, False), console)
    run_one(processor, writer, yes_posting(processor))

    [failed] = workspace.error.glob("*/*_Acme_Corp_Head_of_IT")
    log = (failed / "log.log").read_text()
    assert "create_cv failed" in log
    assert "could not fetch the server log" in log


def test_a_broken_spreadsheet_costs_a_warning_and_not_the_cv(workspace, writer, console):
    class Broken:
        def record(self, job_dir, analysis, cv=None):
            raise RuntimeError("applications.xlsx has no date column")

    processor = WorkingProcessor(workspace, writer, Broken(), console)
    run_one(processor, writer, yes_posting(processor))

    delivered = workspace.cv / day() / "Acme_Corp_Head_of_IT"
    log = (delivered / "log.log").read_text()
    assert "could not record this job in applications.xlsx" in log
    assert "has no date column" in log
    assert processor.failures == 0


def test_debug_folds_in_the_server_log(api, config, workspace, console):
    writer = CvWriter(Calls(api, debug=True), config)
    processor = WorkingProcessor(workspace, writer, build_tracker(workspace.root, False), console)
    run_one(processor, writer, yes_posting(processor))

    log = (workspace.cv / day() / "Acme_Corp_Head_of_IT" / "log.log").read_text()
    assert "--- server request test-request (1 line(s)) ---" in log
    assert "prompt=10, completion=20" in log


def test_a_folder_gone_from_the_queue_is_skipped(processor, writer, workspace, api):
    folder = yes_posting(processor)
    processor.discard(folder)
    run_one(processor, writer, folder)
    assert api.calls == []


def test_the_stored_document_is_the_reply_kept_exactly_as_it_arrived(
        processor, writer, workspace, api):
    """One flat object, not read here at all: a server that learns to write
    one more field must not mean a client to upgrade first."""
    run_one(processor, writer, yes_posting(processor))

    stored = json.loads((workspace.cv / day() / "Acme_Corp_Head_of_IT"
                         / "cv_jordan_rivera_head_of_it.json").read_text())
    assert stored == api.rendered.document


def test_your_candidate_data_is_sent_so_the_page_count_is_real(processor, writer, api):
    run_one(processor, writer, yes_posting(processor))
    assert json.loads(api.seen_candidate_data)["name"] == "Jordan Rivera"


def test_your_own_prompts_and_template_are_sent(api, config, workspace, console, tmp_path):
    prompt = tmp_path / "sys_prompt_cv.txt"
    prompt.write_text("MY PROMPT")
    template = tmp_path / "resume.tex.jinja"
    template.write_text("MY TEMPLATE")
    files = {**config.files, "sys_prompt_cv.txt": prompt, "resume.tex.jinja": template}
    writer = CvWriter(Calls(api), replace(config, files=files))
    processor = WorkingProcessor(workspace, writer, build_tracker(workspace.root, False), console)
    run_one(processor, writer, yes_posting(processor))

    assert api.seen_prompts == {"sys_prompt_cv": "MY PROMPT"}
    assert api.seen_template == "MY TEMPLATE"
    assert "candidate_signature.png" in api.seen_images


def test_each_new_status_is_reported_as_it_happens(processor, writer, workspace, api):
    """The wait is minutes long; a silent one is indistinguishable from a
    hung one."""
    api.statuses = [
        CVStatus(status="generate", detail=""),
        CVStatus(status="review", detail="generation finished, tokens used=99"),
        CVStatus(status="END", detail="done"),
    ]
    run_one(processor, writer, yes_posting(processor))

    log = (workspace.cv / day() / "Acme_Corp_Head_of_IT" / "log.log").read_text()
    assert "generate" in log and "review" in log and "END" in log
    assert "tokens used=99" not in log, "that is what --verbose is for"


def test_verbose_adds_what_the_server_said_about_each_step(api, config, workspace, console):
    api.statuses = [
        CVStatus(status="review", detail="generation finished, tokens used=99"),
        CVStatus(status="END", detail="done"),
    ]
    writer = CvWriter(Calls(api), replace(config, verbose=True))
    processor = WorkingProcessor(workspace, writer, build_tracker(workspace.root, False), console)
    run_one(processor, writer, yes_posting(processor))

    log = (workspace.cv / day() / "Acme_Corp_Head_of_IT" / "log.log").read_text()
    assert "tokens used=99" in log


def test_a_quiet_run_never_asks_for_the_server_log(processor, writer, api):
    run_one(processor, writer, yes_posting(processor))
    assert "logs" not in api.calls, "a successful run costs one round trip per step"


def test_tracking_can_be_turned_off(api, config, workspace, console):
    writer = CvWriter(Calls(api), config)
    processor = WorkingProcessor(workspace, writer, build_tracker(workspace.root, False), console)
    run_one(processor, writer, yes_posting(processor))
    assert not (workspace.root / "applications.xlsx").exists()


def test_resume_picks_up_the_job_instead_of_starting_one(api, config, workspace, console):
    """submit --resume: the job is already running on the server."""
    writer = CvWriter(Calls(api), config, resume="earlier-request")
    processor = WorkingProcessor(workspace, writer, build_tracker(workspace.root, False), console)
    run_one(processor, writer, yes_posting(processor))

    assert api.calls == ["cv_status", "cv_result"], "nothing submitted, nothing paid twice"
    assert (workspace.cv / day() / "Acme_Corp_Head_of_IT"
            / "cv_jordan_rivera_head_of_it.pdf").is_file()


def test_drain_writes_everything_queued_then_returns(processor, writer, workspace, api):
    """submit's way: the CV on the calling thread, and back when it is filed."""
    processor.submit(JD_TEXT, analysis(should_apply="YES", company_name="Alpha"),
                     TaggedLog(processor.console, "a.txt"))
    processor.submit(JD_TEXT, analysis(should_apply="YES", company_name="Beta"),
                     TaggedLog(processor.console, "b.txt"))

    GenerationWorker(processor, writer, processor.console).drain()

    assert sorted(p.name for p in workspace.cv.glob("*/*")) == [
        "Alpha_Head_of_IT", "Beta_Head_of_IT"]
    assert processor.generations.empty()
    assert not any(workspace.working.iterdir())
