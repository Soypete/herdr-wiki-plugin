"""CLI + opencode skill: the agent-context lookup path (search/capture)."""

import json
import re
from pathlib import Path

import haikei_wiki.cli as cli

ROOT = Path(__file__).resolve().parent.parent
STARTER = ROOT / "haikei_wiki" / "starter_tbox.toml"


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


def test_cli_inbox_lists_pending_records_newest_first(tmp_path, monkeypatch, capsys):
    wiki = _isolate(tmp_path, monkeypatch)
    inbox = wiki / "inbox"
    inbox.mkdir()
    records = [
        {
            "id": "older-1",
            "title": "Older capture",
            "entity_type": "claim",
            "content": "older body",
            "created_at": "2026-11-14T10:00:00",
        },
        {
            "id": "newer-1",
            "title": "Newer capture",
            "entity_type": "decision",
            "content": "newer body",
            "created_at": "2026-11-15T10:00:00",
        },
    ]
    for record in records:
        (inbox / f"{record['id']}.json").write_text(json.dumps(record))
    processed = inbox / "processed"
    processed.mkdir()
    (processed / "settled.json").write_text(json.dumps(records[0]))

    rc = cli.main(["inbox", "--json"])
    data = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert [row["path"] for row in data["results"]] == [
        "inbox:newer-1",
        "inbox:older-1",
    ]
    assert [row["source"] for row in data["results"]] == ["inbox", "inbox"]
    assert data["results"][0]["title"] == "Newer capture"
    assert data["results"][0]["entity_type"] == "decision"
    assert "newer body" in data["results"][0]["snippet"]


def test_cli_inbox_empty_json_has_no_results(tmp_path, monkeypatch, capsys):
    _isolate(tmp_path, monkeypatch)

    rc = cli.main(["inbox", "--json"])
    data = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert data["results"] == []


def test_cli_capture_out_of_vocabulary_rejected(tmp_path, monkeypatch):
    wiki = _isolate(tmp_path, monkeypatch)
    rc = cli.main(
        ["capture", "--title", "x", "--type", "sw:Beginner", "--content", "y"]
    )
    assert rc == 2
    assert not (wiki / "inbox").exists() or not list((wiki / "inbox").glob("*.json"))


def test_opencode_skill_present_with_required_frontmatter():
    skill = ROOT / ".opencode" / "skills" / "wiki" / "SKILL.md"
    assert skill.exists(), "opencode skill SKILL.md is missing"
    text = skill.read_text()
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert m, "SKILL.md must start with YAML frontmatter"
    fm = m.group(1)
    assert re.search(r"^name: wiki$", fm, re.M), "frontmatter must set name: wiki"
    assert re.search(r"^description: .+", fm, re.M), "frontmatter must set description"


def test_opencode_config_allows_expected_skills():
    cfg = json.loads((ROOT / "opencode.json").read_text())
    skills = cfg.get("permission", {}).get("skill", {})
    assert skills.get("wiki") == "allow", "permission.skill.wiki must be 'allow'"
    assert skills.get("herdr-orchestrator") == "allow", (
        "permission.skill.herdr-orchestrator must be 'allow'"
    )
    assert skills.get("worker-git-identity") == "allow", (
        "permission.skill.worker-git-identity must be 'allow'"
    )
    # minimal + scoped: no unrelated skill permissions are introduced
    assert set(skills) == {"wiki", "herdr-orchestrator", "worker-git-identity"}
