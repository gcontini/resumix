"""Stage 3: a CV written, filed and recorded — or failed and kept."""

from __future__ import annotations

from dataclasses import replace

import openpyxl
import pytest

from resumix_client.stages.calls import Calls
from resumix_client.stages.generation import CvWriter, GenerationWorker
from resumix_client.stages.terminal import TaggedLog
from resumix_client.stages.working import WorkingProcessor
from resumix_client.tracking import build_tracker
from resumix_client.workspace import day

from conftest import JD_TEXT, analysis


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
        "analysis.json", "candidate_signature.png", "cv_Jordan_Rivera.json",
        "cv_Jordan_Rivera.pdf", "cv_Jordan_Rivera.tex", "jd.txt", "log.log",
    ]
    assert not folder.exists()
    assert api.calls == ["create_cv", "cv_status", "cv_result"]
    assert "writing the CV" in (delivered / "log.log").read_text()


def test_a_generated_cv_gets_a_spreadsheet_row_pointing_at_its_pdf(processor, writer, workspace):
    run_one(processor, writer, yes_posting(processor))

    recorded = row(workspace)
    assert (recorded["company_name"], recorded["job_title"]) == ("Acme Corp", "Head of IT")
    assert recorded["cv_path"] == str(workspace.cv / day() / "Acme_Corp_Head_of_IT"
                                      / "cv_Jordan_Rivera.pdf")


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
    assert (delivered / "cv_Jordan_Rivera.pdf").is_file() is (mode != "letter_only")
    cv_path = row(workspace)["cv_path"]
    if mode == "letter_only":
        assert cv_path is None
    else:
        assert cv_path.endswith("cv_Jordan_Rivera.pdf")


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
    assert processor.failures == 1
    assert not (workspace.root / "applications.xlsx").exists()


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
