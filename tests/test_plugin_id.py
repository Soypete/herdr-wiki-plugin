"""Plugin id herdr.wiki: manifest, legacy config fallback, no stray old id.

Owner decision 2026-11-15: the plugin id changed from haikei.wiki to
herdr.wiki. herdr names each plugin's config dir by its id, so the rename
moved where tbox.toml lives; the loader falls back to the legacy dir (and
prints a one-line stderr hint) instead of silently re-seeding a starter
vocabulary over the user's customized one.
"""

import re
import subprocess
import tomllib
from pathlib import Path

from haikei_wiki.vocabulary import (
    LEGACY_PLUGIN_ID,
    PLUGIN_ID,
    config_dir,
    legacy_config_dir,
    load_vocabulary,
    seed_config_dir,
    vocabulary_path,
)

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "herdr-plugin.toml"
STARTER = ROOT / "haikei_wiki" / "starter_tbox.toml"

# Files that may still mention the old id, each for a stated reason:
# - CHANGELOG.md / README.md: the migration note must name the old id
# - haikei_wiki/vocabulary.py: the intentional legacy-path constant + hint
# - scripts/com.haikei.wiki-organize.plist: launchd label intentionally
#   unchanged (renaming it is not a one-line change; it needs unload/load
#   docs for existing installs)
# - skills/README.md: points at that unchanged launchd plist
# - tests/test_plugin_id.py: this sweep itself names the old id
ALLOWED_LEGACY_ID_FILES = {
    "CHANGELOG.md",
    "README.md",
    "haikei_wiki/vocabulary.py",
    "scripts/com.haikei.wiki-organize.plist",
    "skills/README.md",
    "tests/test_plugin_id.py",
}


def _manifest() -> dict:
    with open(MANIFEST, "rb") as f:
        return tomllib.load(f)


def _isolate_config(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    monkeypatch.setenv("HERDR_PLUGIN_CONFIG_DIR", str(cfg))
    return cfg, tmp_path / "haikei.wiki"


def _write_legacy_tbox(legacy_dir: Path) -> Path:
    """A minimal customized legacy vocabulary the user would have edited."""
    legacy_dir.mkdir(parents=True, exist_ok=True)
    tbox = legacy_dir / "tbox.toml"
    tbox.write_text(
        '[entity_types]\n'
        'legacy_type = "a type only the user\'s legacy file has"\n\n'
        "[link_predicates]\n"
        'legacy_predicate = "a predicate only the user\'s legacy file has"\n'
    )
    return tbox


# --- the manifest ---------------------------------------------------------


def test_manifest_id_is_herdr_wiki():
    manifest = _manifest()
    assert manifest["id"] == "herdr.wiki"


def test_manifest_name_matches_the_id():
    manifest = _manifest()
    assert manifest["name"] == "Herdr Wiki"


def test_manifest_actions_keep_their_ids():
    manifest = _manifest()
    assert [a["id"] for a in manifest["actions"]] == [
        "search",
        "capture",
        "organize",
        "context-dump",
    ]


def test_manifest_action_commands_use_the_new_id():
    manifest = _manifest()
    commands = [
        key["command"]
        for key in manifest["keys"]["command"]
        if key.get("type") == "plugin_action"
    ]
    assert commands, "manifest defines no plugin_action keybindings"
    for command in commands:
        assert command.startswith(f"{PLUGIN_ID}.")
        assert not command.startswith(f"{LEGACY_PLUGIN_ID}.")


def test_action_entrypoints_pass_the_manifest_id():
    """bin/ entrypoints must open panes under the manifest's plugin id."""
    manifest = _manifest()
    for rel in ("bin/wiki_search.py", "bin/wiki_capture.py"):
        text = (ROOT / rel).read_text()
        match = re.search(r'^PLUGIN_ID = "(.+)"$', text, re.M)
        assert match, f"{rel} has no PLUGIN_ID constant"
        assert match.group(1) == manifest["id"]


# --- config dir resolution ------------------------------------------------


def test_config_dir_honors_herdr_env(tmp_path, monkeypatch):
    cfg, _ = _isolate_config(tmp_path, monkeypatch)
    assert config_dir() == cfg


def test_default_config_dir_is_named_by_the_new_id(monkeypatch):
    monkeypatch.delenv("HERDR_PLUGIN_CONFIG_DIR", raising=False)
    assert config_dir() == (
        Path.home() / ".config" / "herdr" / "plugins" / "herdr.wiki"
    )


def test_legacy_config_dir_is_the_sibling_named_by_the_legacy_id(
    tmp_path, monkeypatch
):
    cfg, _ = _isolate_config(tmp_path, monkeypatch)
    assert legacy_config_dir() == cfg.parent / "haikei.wiki"


# --- legacy tbox.toml fallback --------------------------------------------


def test_vocabulary_path_prefers_the_new_config_dir(tmp_path, monkeypatch, capsys):
    cfg, legacy = _isolate_config(tmp_path, monkeypatch)
    (cfg / "tbox.toml").write_text(STARTER.read_text())
    _write_legacy_tbox(legacy)

    assert vocabulary_path() == cfg / "tbox.toml"
    assert capsys.readouterr().err == ""


def test_vocabulary_path_falls_back_to_legacy_tbox_and_hints_once(
    tmp_path, monkeypatch, capsys
):
    cfg, legacy = _isolate_config(tmp_path, monkeypatch)
    legacy_tbox = _write_legacy_tbox(legacy)

    assert vocabulary_path() == legacy_tbox
    err = capsys.readouterr().err
    assert "haikei.wiki" in err
    assert "herdr.wiki" in err
    assert err.strip().count("\n") == 0, "the migration hint must be one line"


def test_vocabulary_path_without_any_tbox_points_at_the_new_dir(
    tmp_path, monkeypatch, capsys
):
    cfg, _ = _isolate_config(tmp_path, monkeypatch)

    assert vocabulary_path() == cfg / "tbox.toml"
    assert capsys.readouterr().err == ""


def test_load_vocabulary_reads_the_legacy_file(tmp_path, monkeypatch, capsys):
    cfg, legacy = _isolate_config(tmp_path, monkeypatch)
    _write_legacy_tbox(legacy)

    vocab = load_vocabulary()
    assert "legacy_type" in vocab.entity_types
    assert "legacy_predicate" in vocab.link_predicates
    assert capsys.readouterr().err  # the hint was shown


def test_seeding_does_not_shadow_a_legacy_vocabulary(tmp_path, monkeypatch):
    """No starter tbox.toml is written while the user's legacy file exists."""
    cfg, legacy = _isolate_config(tmp_path, monkeypatch)
    _write_legacy_tbox(legacy)

    vocab = load_vocabulary()
    assert not (cfg / "tbox.toml").exists()
    assert "legacy_type" in vocab.entity_types


def test_seeding_still_seeds_without_a_legacy_dir(tmp_path, monkeypatch, capsys):
    cfg, _ = _isolate_config(tmp_path, monkeypatch)

    vocab = load_vocabulary()
    assert (cfg / "tbox.toml").read_text() == STARTER.read_text()
    assert vocab.entity_types
    assert capsys.readouterr().err == ""


def test_seed_config_dir_creates_the_new_dir(tmp_path, monkeypatch):
    cfg, _ = _isolate_config(tmp_path, monkeypatch)

    assert seed_config_dir() == cfg
    assert cfg.is_dir()


# --- no stray old id in tracked files -------------------------------------


def test_no_stray_legacy_id_in_tracked_files():
    proc = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    )
    tracked = [line for line in proc.stdout.splitlines() if line]
    assert tracked, "git ls-files returned nothing; run from the repo?"

    offenders = []
    for rel in tracked:
        if rel in ALLOWED_LEGACY_ID_FILES:
            continue
        path = ROOT / rel
        if not path.is_file():
            continue
        if LEGACY_PLUGIN_ID in path.read_text(encoding="utf-8", errors="replace"):
            offenders.append(rel)
    assert offenders == [], (
        f"the legacy plugin id {LEGACY_PLUGIN_ID} still appears in: {offenders}; "
        "only the intentional legacy-path constant and the migration notes may "
        "name it"
    )
