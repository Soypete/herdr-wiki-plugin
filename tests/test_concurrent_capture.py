"""Two CONCURRENT captures from two panes both land, with no corruption.

Simulates two agents in two different panes/workspaces capturing at the same
time by running two real subprocesses (the plugin's own capture entrypoint)
in parallel against the same wiki. Each process gets its own
HERDR_PLUGIN_CONTEXT_JSON, just like Herdr would inject per pane.

Run with: python3 -m pytest tests/test_concurrent_capture.py -v
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CAPTURE_SCRIPT = REPO_ROOT / "bin" / "wiki_capture.py"


def test_two_concurrent_captures_from_two_panes_both_land(tmp_path: Path):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "log.md").write_text("# Wiki Log\n\n## Chronological Record\n")
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    ctx_a = json.dumps(
        {
            "workspace_id": "wA",
            "workspace_label": "alpha",
            "workspace_cwd": "/tmp/alpha",
            "tab_id": "wA:t1",
            "tab_label": "1",
            "focused_pane_id": "wA:p1",
            "focused_pane_cwd": "/tmp/alpha",
            "focused_pane_agent": "claude",
            "focused_pane_status": "working",
            "invocation_source": "keybinding",
        }
    )
    ctx_b = json.dumps(
        {
            "workspace_id": "wB",
            "workspace_label": "beta",
            "workspace_cwd": "/tmp/beta",
            "tab_id": "wB:t1",
            "tab_label": "1",
            "focused_pane_id": "wB:p1",
            "focused_pane_cwd": "/tmp/beta",
            "focused_pane_agent": "codex",
            "focused_pane_status": "working",
            "invocation_source": "keybinding",
        }
    )
    common = {"WIKI_PATH": str(wiki), "HERDR_PLUGIN_CONFIG_DIR": str(config_dir)}

    # Launch both captures concurrently (two panes, two agents).
    pa = subprocess.Popen(
        [
            sys.executable,
            str(CAPTURE_SCRIPT),
            "--title",
            "claim from pane A",
            "--type",
            "claim",
            "--content",
            "Agent A observed something worth keeping.",
        ],
        env={
            **os.environ,
            **common,
            "HERDR_BIN_PATH": "/nonexistent/herdr-for-test",
            "HERDR_PLUGIN_CONTEXT_JSON": ctx_a,
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    pb = subprocess.Popen(
        [
            sys.executable,
            str(CAPTURE_SCRIPT),
            "--title",
            "claim from pane B",
            "--type",
            "claim",
            "--content",
            "Agent B observed something else worth keeping.",
            "--link",
            "derived_from:imported/whitepaper",
            "--link",
            "contradicts:claim-from-pane-a",
        ],
        env={
            **os.environ,
            **common,
            "HERDR_BIN_PATH": "/nonexistent/herdr-for-test",
            "HERDR_PLUGIN_CONTEXT_JSON": ctx_b,
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    out_a, err_a = pa.communicate(timeout=60)
    out_b, err_b = pb.communicate(timeout=60)
    assert pa.returncode == 0, f"pane A capture failed: {out_a} {err_a}"
    assert pb.returncode == 0, f"pane B capture failed: {out_b} {err_b}"

    inbox = wiki / "inbox"
    files = sorted(inbox.glob("*.json"))
    assert len(files) == 2, f"expected 2 inbox records, got {len(files)}: {files}"

    records = {}
    for f in files:
        record = json.loads(f.read_text())  # must parse: no corruption
        records[record["title"]] = record

    rec_a = records["claim from pane A"]
    rec_b = records["claim from pane B"]
    assert rec_a["provenance"]["workspace"] == "wA"
    assert rec_a["provenance"]["pane"] == "wA:p1"
    assert rec_a["provenance"]["agent"] == "claude"
    assert rec_b["provenance"]["workspace"] == "wB"
    assert rec_b["provenance"]["pane"] == "wB:p1"
    assert rec_b["provenance"]["agent"] == "codex"
    assert rec_a["content"] == "Agent A observed something worth keeping."
    assert rec_b["content"] == "Agent B observed something else worth keeping."
    # links survive intact (no corrupted link structure)
    assert rec_b["links"] == [
        {"predicate": "derived_from", "target": "imported/whitepaper"},
        {"predicate": "contradicts", "target": "claim-from-pane-a"},
    ]
    assert rec_a["links"] == []

    # log.md: exactly two well-formed capture lines, none interleaved/corrupt
    log = (wiki / "log.md").read_text()
    capture_lines = re.findall(r"^## \[\d{4}-\d{2}-\d{2}\] capture \| (.+)$", log, re.M)
    assert sorted(capture_lines) == ["claim from pane A", "claim from pane B"]
    # every entry line in the log is well-formed (template headers allowed)
    headers = {"## Chronological Record"}
    for line in log.splitlines():
        if line.startswith("## ") and line not in headers:
            assert re.match(r"^## \[\d{4}-\d{2}-\d{2}\] \w+ \| .+$", line), (
                f"corrupt log line: {line!r}"
            )
