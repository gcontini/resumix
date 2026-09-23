"""``PromptConfirmer``: only y/n/s/q or a URL are ever accepted."""

from __future__ import annotations

from typing import Iterator, List

import pytest

from resumix_client.ui import PromptConfirmer

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
