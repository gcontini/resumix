"""``PromptConfirmer``: only y/n/s/q or a URL are ever accepted.

And for a posting discarded before, only r/s/q."""

from __future__ import annotations

from pathlib import Path
from typing import Iterator, List

import pytest

from resumix_client.ui import AutoConfirmer, PromptConfirmer

from conftest import analysis


def _confirm(monkeypatch, *answers: str):
    """Feed ``answers`` to ``input()`` in order and return the decision."""
    it: Iterator[str] = iter(answers)

    def fake_input(prompt: str = "") -> str:
        return next(it)

    monkeypatch.setattr("builtins.input", fake_input)
    return PromptConfirmer().confirm(analysis())


@pytest.mark.parametrize("answer", ["y", "Y", "yes", "YES", "  y  "])
def test_yes_submits_without_a_url(monkeypatch, answer):
    decision = _confirm(monkeypatch, answer)
    assert decision.submit and decision.url is None and not decision.quit


@pytest.mark.parametrize("answer", ["n", "s", "skip", "N", "S", "  s  "])
def test_no_or_skip_discards(monkeypatch, answer):
    decision = _confirm(monkeypatch, answer)
    assert not decision.submit and not decision.quit


@pytest.mark.parametrize("answer", ["q", "quit", "Q", "  q  "])
def test_quit_stops_the_run(monkeypatch, answer):
    decision = _confirm(monkeypatch, answer)
    assert not decision.submit and decision.quit


def test_a_url_submits_with_it(monkeypatch):
    decision = _confirm(monkeypatch, "https://jobs.example/42")
    assert decision.submit and decision.url == "https://jobs.example/42"


def test_blank_input_is_ignored_and_asks_again(monkeypatch):
    decision = _confirm(monkeypatch, "   ", "\t", "s")
    assert not decision.submit and not decision.quit


@pytest.mark.parametrize("garbage", ["ss", "maybe", "yy", "sure", "nope", "42"])
def test_anything_else_is_rejected_and_asks_again_instead_of_submitting(monkeypatch, garbage):
    """A mistyped skip (or anything not y/n/s/q/URL) must never fall through
    to an implicit submit — that is exactly what let a stray keystroke turn
    into a real CV job."""
    decision = _confirm(monkeypatch, garbage, "s")
    assert not decision.submit and not decision.quit


def test_eof_quits(monkeypatch):
    def fake_input(prompt: str = "") -> str:
        raise EOFError

    monkeypatch.setattr("builtins.input", fake_input)
    decision = PromptConfirmer().confirm(analysis())
    assert not decision.submit and decision.quit


# --- a posting discarded before ---------------------------------------------
def _resubmit(monkeypatch, *answers: str) -> str:
    it: Iterator[str] = iter(answers)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(it))
    return PromptConfirmer().resubmit(Path("discarded/26-09-01/Acme_Corp_Head_of_IT"))


@pytest.mark.parametrize("answer, expected", [
    ("r", "resubmit"), ("R", "resubmit"), ("resubmit", "resubmit"),
    ("s", "skip"), ("skip", "skip"), ("q", "quit"), ("  Q ", "quit"),
])
def test_a_discarded_posting_asks_resubmit_skip_or_quit(monkeypatch, answer, expected):
    assert _resubmit(monkeypatch, answer) == expected


@pytest.mark.parametrize("garbage", ["y", "", "n", "maybe"])
def test_a_discarded_posting_asks_again_on_anything_else(monkeypatch, garbage):
    assert _resubmit(monkeypatch, garbage, "s") == "skip"


def test_a_discarded_posting_quits_on_eof(monkeypatch):
    def fake_input(prompt: str = "") -> str:
        raise EOFError

    monkeypatch.setattr("builtins.input", fake_input)
    assert PromptConfirmer().resubmit(Path("x")) == "quit"


def test_yes_skips_a_discarded_posting_without_asking(monkeypatch):
    def no_input(prompt: str = "") -> str:
        raise AssertionError("--yes must never wait for an answer")

    monkeypatch.setattr("builtins.input", no_input)
    assert AutoConfirmer().resubmit(Path("x")) == "skip"
