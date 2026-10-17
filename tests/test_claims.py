"""Structured claims (issue #10): path-level claims, sequence reservations,
overlap flagging, and PR-vs-claim collision audit."""

import json
from pathlib import Path

import haikei_wiki.cli as cli
import haikei_wiki.claims as claims

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
    monkeypatch.setenv("HERDR_PLUGIN_STATE_DIR", str(tmp_path / "state"))
    return wiki


def _run(args, capsys):
    rc = cli.main(args)
    return rc, capsys.readouterr()


def test_claim_create_list_release(tmp_path, monkeypatch, capsys):
    _isolate(tmp_path, monkeypatch)
    rc, out = _run(
        [
            "claim",
            "--repo",
            "HaikeiLabs/kei",
            "--paths",
            "SKILL.md,evals/**",
            "--pr",
            "24",
            "--owner",
            "orch-1",
        ],
        capsys,
    )
    assert rc == 0
    cid = out.out.strip().splitlines()[-1]
    assert cid

    rc, out = _run(["claims", "--json"], capsys)
    assert rc == 0
    data = json.loads(out.out)
    assert len(data["claims"]) == 1
    c = data["claims"][0]
    assert c["repo"] == "HaikeiLabs/kei"
    assert c["paths"] == ["SKILL.md", "evals/**"]
    assert c["pr"] == 24

    rc, out = _run(["release", cid], capsys)
    assert rc == 0
    rc, out = _run(["claims", "--json"], capsys)
    data = json.loads(out.out)
    assert data["claims"] == []


def test_claims_flag_overlapping_paths(tmp_path, monkeypatch, capsys):
    _isolate(tmp_path, monkeypatch)
    _run(["claim", "--repo", "O/r", "--paths", "cmd/server", "--branch", "b1"], capsys)
    rc, out = _run(
        ["claim", "--repo", "O/r", "--paths", "cmd/server/**", "--branch", "b2"], capsys
    )
    assert rc == 0
    rc, out = _run(["claims", "--json"], capsys)
    data = json.loads(out.out)
    overlaps = data["overlaps"]
    assert overlaps and overlaps[0]["kind"] == "path_overlap"
    assert overlaps[0]["paths"]


def test_claims_flag_duplicate_reservations(tmp_path, monkeypatch, capsys):
    _isolate(tmp_path, monkeypatch)
    rc, out = _run(
        [
            "reserve",
            "--repo",
            "HaikeiLabs/kei-policy-catalog",
            "--kind",
            "migration",
            "--value",
            "074",
        ],
        capsys,
    )
    assert rc == 0
    # the second orchestrator reserves the same migration
    rc, out = _run(
        [
            "reserve",
            "--repo",
            "HaikeiLabs/kei-policy-catalog",
            "--kind",
            "migration",
            "--value",
            "074",
        ],
        capsys,
    )
    assert rc == 0  # accepted but flagged
    rc, out = _run(["claims", "--json"], capsys)
    data = json.loads(out.out)
    conflicts = [o for o in data["overlaps"] if o["kind"] == "reservation_conflict"]
    assert conflicts
    assert conflicts[0]["sequence"] == "migration 074"


def test_distant_migration_reservations_do_not_conflict(tmp_path, monkeypatch, capsys):
    _isolate(tmp_path, monkeypatch)
    _run(["reserve", "--repo", "O/r", "--kind", "migration", "--value", "074"], capsys)
    _run(["reserve", "--repo", "O/r", "--kind", "migration", "--value", "075"], capsys)
    rc, out = _run(["claims", "--json"], capsys)
    data = json.loads(out.out)
    assert data["overlaps"] == []


def test_expired_claim_is_inactive(tmp_path, monkeypatch, capsys):
    _isolate(tmp_path, monkeypatch)
    rc, out = _run(
        ["claim", "--repo", "O/r", "--paths", "x/**", "--expires", "0h"], capsys
    )
    assert rc == 0
    rc, out = _run(["claims", "--json"], capsys)
    data = json.loads(out.out)
    assert data["claims"] == []


def test_collisions_reports_unclaimed_and_undiffed_prs(tmp_path, monkeypatch, capsys):
    _isolate(tmp_path, monkeypatch)
    # active claim for PR 24 (branch b-a) with unclaimed extra file
    _run(
        [
            "claim",
            "--repo",
            "O/r",
            "--paths",
            "skill-a/**",
            "--pr",
            "24",
            "--branch",
            "b-a",
        ],
        capsys,
    )
    # active unrelated claim
    _run(
        [
            "claim",
            "--repo",
            "O/r",
            "--paths",
            "skill-c/**",
            "--pr",
            "25",
            "--branch",
            "b-c",
        ],
        capsys,
    )

    fake = json.dumps(
        {
            "pr_list": [
                {
                    "number": 24,
                    "headRefName": "b-a",
                    "files": [{"path": "skill-a/SKILL.md"}, {"path": "evals/x.json"}],
                },
                {
                    "number": 30,
                    "headRefName": "b-z",
                    "files": [{"path": "misc/Readme"}],
                },
            ]
        }
    )

    class FakeGH:
        def __init__(self, *_a, **_k):
            self.calls = []

        def run(self, *a, **k):
            self.calls.append(a)
            out = fake

            class R:
                returncode = 0

                def __init__(self, stdout):
                    self.stdout = stdout

            return R(out)

    # monkeypatch claims.gh_open_prs
    def fake_open_prs(repo, gh_bin="gh", timeout=0.0):
        if repo != "O/r":
            return None
        return [
            (24, "b-a", ["skill-a/SKILL.md", "evals/x.json"]),
            (30, "b-z", ["misc/Readme"]),
        ]

    monkeypatch.setattr(claims, "gh_open_prs", fake_open_prs)
    rc, out = (
        _run(["wiki", "audit", "--collisions"], capsys)
        if False
        else _run(["audit", "--collisions"], capsys)
    )
    assert rc == 0
    text = out.out
    assert "O/r" in text
    # PR 30 has no claim at all
    assert "#30" in text
    # PR 24 claimed, but also touches unclaimed evals/x.json
    assert "evals/x.json" in text


def test_collisions_json_shape(tmp_path, monkeypatch, capsys):
    _isolate(tmp_path, monkeypatch)
    _run(["claim", "--repo", "O/r", "--paths", "a/**", "--pr", "1"], capsys)
    monkeypatch.setattr(
        claims,
        "gh_open_prs",
        lambda repo, gh_bin="gh", timeout=0.0: [(1, "b", ["a/f"])],
    )
    rc, out = _run(["audit", "--collisions", "--json"], capsys)
    assert rc == 0
    data = json.loads(out.out)
    assert data["collisions"]["O/r"]["unclaimed_prs"] == []
    assert data["collisions"]["O/r"]["claims_vs_pr"] == []


def test_gh_offline_degrades_to_note(tmp_path, monkeypatch, capsys):
    _isolate(tmp_path, monkeypatch)
    _run(["claim", "--repo", "O/r", "--paths", "a/**"], capsys)
    rc, out = _run(["audit", "--collisions"], capsys)
    assert rc == 0
    assert "gh unavailable" in out.err or "gh unavailable" in out.out
