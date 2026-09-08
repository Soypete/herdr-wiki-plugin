"""CLI + opencode skill: the agent-context lookup path (search/capture)."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

import haikei_wiki.cli as cli

STARTER = Path(__file__).resolve().parent.parent / "haikei_wiki" / "starter_tbox.toml"


def _load_skill():
    p = Path(__file__).resolve().parent.parent / "skills" / "wiki.py"
    spec = importlib.util.spec_from_file_location("wiki_skill", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_wiki(tmp_path: Path) -> Path:
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "log.md").write_text("# Wiki Log\n")
    return wiki


def _isolate(tmp_path: Path, monkeypatch) -> Path:
    wiki = _make_wiki(tmp_path)
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / "tbox.toml").write_text(STARTER.read_text())
    monkeypatch.setenv("WIKI_PATH", str(wiki))
    monkeypatch.setenv("HERDR_PLUGIN_CONFIG_DIR", str(cfg))
    return wiki


def test_cli_capture_valid_lands_in_inbox(tmp_path, monkeypatch):
    wiki = _isolate(tmp_path, monkeypatch)
    rc = cli.main(
        [
            "capture",
            "--title",
            "agent note",
            "--type",
            "claim",
            "--content",
            "durable finding",
            "--link",
            "derived_from:imported/x",
        ]
    )
    assert rc == 0
    records = list((wiki / "inbox").glob("*.json"))
    assert len(records) == 1
    rec = json.loads(records[0].read_text())
    assert rec["entity_type"] == "claim"
    assert rec["links"] == [{"predicate": "derived_from", "target": "imported/x"}]


def test_cli_capture_out_of_vocabulary_rejected(tmp_path, monkeypatch):
    wiki = _isolate(tmp_path, monkeypatch)
    rc = cli.main(
        ["capture", "--title", "x", "--type", "sw:Beginner", "--content", "y"]
    )
    assert rc == 2
    assert not (wiki / "inbox").exists() or not list((wiki / "inbox").glob("*.json"))


def test_skill_defaults_bare_query_to_search(monkeypatch):
    mod = _load_skill()
    seen = {}

    def fake(argv):
        seen["argv"] = argv
        return 0

    monkeypatch.setattr(mod, "main", fake)
    monkeypatch.setattr(sys, "argv", ["wiki.py", "whitepaper", "--top-k", "2"])
    with pytest.raises(SystemExit):
        mod.run()
    assert seen["argv"] == ["search", "whitepaper", "--top-k", "2"]


def test_skill_passes_subcommand_through(monkeypatch):
    mod = _load_skill()
    seen = {}

    def fake(argv):
        seen["argv"] = argv
        return 0

    monkeypatch.setattr(mod, "main", fake)
    monkeypatch.setattr(sys, "argv", ["wiki.py", "stats"])
    with pytest.raises(SystemExit):
        mod.run()
    assert seen["argv"] == ["stats"]
