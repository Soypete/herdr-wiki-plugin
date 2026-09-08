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


def test_opencode_config_allows_only_the_wiki_skill():
    cfg = json.loads((ROOT / "opencode.json").read_text())
    skills = cfg.get("permission", {}).get("skill", {})
    assert skills.get("wiki") == "allow", "permission.skill.wiki must be 'allow'"
    # minimal + scoped: no unrelated skill permissions are introduced
    assert set(skills) == {"wiki"}
