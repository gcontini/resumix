"""Is this posting one you have handled before? Pure matching, best effort."""

from __future__ import annotations

import json

import pytest

from resumix_client.duplicates import find_previous, normalize, same_job


def test_normalize_ignores_case_accents_and_spacing():
    assert normalize("  Société   Générale ") == "societe generale"
    assert normalize("ＡＣＭＥ") == "acme"
    assert normalize("Zürich — Data 🚀") == "zurich data"


@pytest.mark.parametrize("value", [None, 42, [], {}])
def test_normalize_treats_anything_but_text_as_absent(value):
    assert normalize(value) == ""


def test_the_same_url_is_the_same_job():
    a = {"posting_url": "https://Jobs.example/42", "company_name": "Acme", "job_title": "CTO"}
    b = {"posting_url": "https://jobs.example/42", "company_name": "Other", "job_title": "Dev"}
    assert same_job(a, b)


def test_the_same_company_and_title_is_the_same_job_even_with_other_urls():
    a = {"posting_url": "https://a/1", "company_name": "Société", "job_title": "Head of IT"}
    b = {"posting_url": "https://b/2", "company_name": "SOCIETE", "job_title": "head of it"}
    assert same_job(a, b)


def test_without_a_url_only_company_and_title_count():
    a = {"company_name": "Acme", "job_title": "CTO"}
    assert same_job(a, {"posting_url": None, "company_name": "acme", "job_title": "cto"})
    assert not same_job(a, {"company_name": "Acme", "job_title": "CIO"})


def test_without_a_title_only_the_url_counts():
    a = {"posting_url": "https://x/1", "company_name": "Acme"}
    assert same_job(a, {"posting_url": "https://x/1"})
    assert not same_job(a, {"company_name": "Acme", "job_title": ""})
    assert not same_job({"company_name": "Acme"}, {"company_name": "Acme"})


def test_nothing_to_compare_is_never_a_match():
    assert not same_job({}, {})
    assert not same_job({"posting_url": ""}, {"posting_url": ""})


def test_find_previous_reads_old_files_as_plain_dicts(tmp_path):
    """Old analyses were written against older schemas: never validated,
    and one that cannot be read is skipped, not fatal."""
    def job(name, content):
        folder = tmp_path / name
        folder.mkdir()
        (folder / "analysis.json").write_text(content, encoding="utf-8")
        return folder

    broken = job("broken", "{not json")
    listed = job("listed", "[1, 2]")
    partial = job("partial", json.dumps({"job_title": "CTO", "legacy_field": 1}))
    match = job("match", json.dumps({"company_name": "Acme", "job_title": "CTO"}))
    missing = tmp_path / "missing"

    current = {"company_name": "ACME", "job_title": "cto", "posting_url": None}
    assert find_previous(current, [missing, broken, listed, partial, match]) == match
    assert find_previous(current, [missing, broken, listed, partial]) is None
