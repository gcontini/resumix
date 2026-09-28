"""Have you seen this posting before?

Every finished or discarded job keeps its ``analysis.json``. Before anything
is spent on a new posting, those are read back — as plain dictionaries, never
validated: they were written by older clients against older schemas, and a
file that no longer parses must not stop a new job. Best effort, not a gate.

Two postings are the same job when their URLs match, or when both the company
and the title match. A side missing its URL is compared by company and title
only; a side missing either of those is compared by URL only.
"""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from .workspace import ANALYSIS_FILENAME


def normalize(value: Any) -> str:
    """Case-, accent- and spacing-blind text; ``""`` for anything absent."""
    if not isinstance(value, str):
        return ""
    ascii_only = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return " ".join(ascii_only.lower().split())


def same_job(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    url_a, url_b = normalize(a.get("posting_url")), normalize(b.get("posting_url"))
    if url_a and url_a == url_b:
        return True
    company_a, company_b = normalize(a.get("company_name")), normalize(b.get("company_name"))
    title_a, title_b = normalize(a.get("job_title")), normalize(b.get("job_title"))
    return bool(company_a and title_a) and (company_a, title_a) == (company_b, title_b)


def find_previous(current: Mapping[str, Any], folders: Iterable[Path]) -> Optional[Path]:
    """The first folder whose ``analysis.json`` describes the same job."""
    for folder in folders:
        try:
            stored = json.loads((folder / ANALYSIS_FILENAME).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(stored, dict) and same_job(current, stored):
            return folder
    return None


__all__ = ["normalize", "same_job", "find_previous"]
