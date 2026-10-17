"""Search must tokenize, rank and normalize — not exact-phrase-only.

Reproduces issue #9's scenarios: non-adjacent multi-word queries, hyphen/
identifier variants, light stemming, and safe literal matching of regex
metacharacters.
"""

import json
from pathlib import Path

import haikei_wiki.cli as cli

ROOT = Path(__file__).resolve().parent.parent
STARTER = ROOT / "haikei_wiki" / "starter_tbox.toml"


def _isolate(tmp_path: Path, monkeypatch) -> Path:
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "log.md").write_text("# Wiki Log\n")
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / "tbox.toml").write_text(STARTER.read_text())
    monkeypatch.setenv("WIKI_PATH", str(wiki))
    monkeypatch.setenv("HERDR_PLUGIN_CONFIG_DIR", str(cfg))
    return wiki


def _seed_inbox(wiki: Path, rid: str, title: str, content: str) -> None:
    inbox = wiki / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / f"{rid}.json").write_text(
        json.dumps(
            {
                "id": rid,
                "title": title,
                "entity_type": "claim",
                "content": content,
                "links": [],
                "provenance": {"agent": "test"},
                "created_at": "2026-10-01T00:00:00",
            }
        )
    )


def _page(wiki: Path, rel: str, text: str) -> Path:
    p = wiki / "wiki" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def test_nonadjacent_terms_match(tmp_path, monkeypatch, capsys):
    wiki = _isolate(tmp_path, monkeypatch)
    _page(
        wiki,
        "decision/dvl-wave.md",
        "---\ntitle: plan DVL wave 1 dispatch 2026-10-01: parallel workers\n"
        "category: decision\ncreated: 2026-10-01T00:00:00\n---\n\nbody\n",
    )
    for query in ("wave dispatch", "parallel workers DVL", "dvl parallel"):
        rc = cli.main(["search", query, "--json"])
        out = capsys.readouterr().out
        assert rc == 0, query
        data = json.loads(out)
        assert any(r["path"].endswith("dvl-wave.md") for r in data["results"]), query


def test_all_terms_rank_above_any(tmp_path, monkeypatch, capsys):
    wiki = _isolate(tmp_path, monkeypatch)
    # matches both terms (body only)
    _page(wiki, "decision/both.md", "alpha beta docs\n")
    # matches only one term
    _page(wiki, "decision/one.md", "alpha only\n")
    rc = cli.main(["search", "alpha beta", "--json"])
    data = json.loads(capsys.readouterr().out)
    scores = {r["path"]: r["score"] for r in data["results"]}
    assert (
        scores[str(wiki / "wiki/decision/both.md")]
        > scores[str(wiki / "wiki/decision/one.md")]
    )


def test_hyphen_identifier_variants_match(tmp_path, monkeypatch, capsys):
    wiki = _isolate(tmp_path, monkeypatch)
    _page(wiki, "decision/adr.md", "decided by ADR-011\n")
    for query in ("adr011", "adr-011", "ADR 011"):
        rc = cli.main(["search", query])
        out = capsys.readouterr().out
        assert rc == 0, query
        assert "adr.md" in out, query


def test_light_stemming(tmp_path, monkeypatch, capsys):
    wiki = _isolate(tmp_path, monkeypatch)
    _page(wiki, "claim/writes.md", "this agent writes findings to the wiki\n")
    rc = cli.main(["search", "write"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "writes.md" in out


def test_regex_metacharacters_are_literal(tmp_path, monkeypatch, capsys):
    wiki = _isolate(tmp_path, monkeypatch)
    _page(wiki, "claim/literal.md", "cost is n.[x] in the ledger\n")
    rc = cli.main(["search", "n.[x]"])
    out = capsys.readouterr().out
    # must not crash and must not match stray regex-expansions
    assert rc in (0, 1)
    if rc == 0:
        assert "literal.md" in out


def test_term_frequency_ranks_repeated_term(tmp_path, monkeypatch, capsys):
    wiki = _isolate(tmp_path, monkeypatch)
    _page(wiki, "claim/a.md", "utilities mentioned once\n")
    _page(wiki, "claim/b.md", "utilities here; utilities everywhere; utilities again\n")
    rc = cli.main(["search", "utilities", "--json"])
    data = json.loads(capsys.readouterr().out)
    scores = {r["path"]: r["score"] for r in data["results"]}
    assert scores[str(wiki / "wiki/claim/b.md")] > scores[str(wiki / "wiki/claim/a.md")]
