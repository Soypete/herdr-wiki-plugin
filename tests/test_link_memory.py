"""Regression test for the link_memory NameError.

adapter.py link_memory referenced an undefined name `metadata`:
    self.wiki.write(source_id, content, metadata.get("category", "general"))
Any successful link raised NameError. This test links two pages and asserts
no exception is raised and the link lands.
"""

from pathlib import Path

from haikei_wiki.adapter import LLMWikiAdapter


def test_link_memory_no_nameerror_and_link_lands(tmp_path: Path):
    adapter = LLMWikiAdapter(tmp_path)

    adapter.write_memory("Content of page A.", {"title": "page-a", "category": "notes"})
    adapter.write_memory("Content of page B.", {"title": "page-b", "category": "notes"})

    # Before the fix this raised NameError: name 'metadata' is not defined.
    ok = adapter.link_memory("page-a", "page-b", "relates_to")

    assert ok is True
    written = (tmp_path / "wiki" / "general" / "page-a.md").read_text()
    assert "[[page-b]]" in written
    assert "See also" in written
