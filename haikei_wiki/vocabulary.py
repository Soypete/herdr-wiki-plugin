"""Closed capture vocabulary loaded from tbox.toml.

The vocabulary is a pure config artifact. It is intentionally shaped like a
minimal T-box (entity types + link predicates) so it can later be replaced by
a proper capture T-box (a new .ttl in the ontologies repo) without changing
plugin code. It is NOT the education T-box
(education/TBOX_LEARNING_SOFTWARE.ttl), which models curricula, not captures.

Enforcement is at the write boundary: a capture whose entity type or link
predicate is not in the loaded vocabulary is rejected. Nothing is normalized
or coerced to a default.
"""

import os
import shutil
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

STARTER_TBOX = Path(__file__).resolve().parent / "starter_tbox.toml"

# The plugin id herdr names config/state dirs by (herdr-plugin.toml).
PLUGIN_ID = "herdr.wiki"
# Pre-rename id: existing installs have their config under this name.
LEGACY_PLUGIN_ID = "haikei.wiki"


class VocabularyViolation(ValueError):
    """A capture violated the closed capture vocabulary."""


@dataclass(frozen=True)
class Vocabulary:
    entity_types: frozenset = field(default_factory=frozenset)
    link_predicates: frozenset = field(default_factory=frozenset)

    def check_entity_type(self, entity_type: str) -> None:
        if entity_type not in self.entity_types:
            allowed = ", ".join(sorted(self.entity_types))
            raise VocabularyViolation(
                f"entity_type '{entity_type}' violates constraint "
                f"'entity_type must be one of the loaded capture vocabulary "
                f"types' (allowed: {allowed})"
            )

    def check_link_predicate(self, predicate: str) -> None:
        if predicate not in self.link_predicates:
            allowed = ", ".join(sorted(self.link_predicates))
            raise VocabularyViolation(
                f"link predicate '{predicate}' violates constraint "
                f"'link predicate must be one of the loaded capture "
                f"vocabulary predicates' (allowed: {allowed})"
            )

    def check_capture(self, entity_type: str, links: list[dict]) -> None:
        if not entity_type:
            raise VocabularyViolation(
                "entity_type is missing; constraint 'entity_type must be one "
                "of the loaded capture vocabulary types' requires an explicit "
                "type - no default is applied"
            )
        self.check_entity_type(entity_type)
        for link in links or []:
            predicate = link.get("predicate", "")
            if not predicate:
                raise VocabularyViolation(
                    "link is missing a predicate; constraint 'link predicate "
                    "must be one of the loaded capture vocabulary predicates' "
                    "requires an explicit predicate"
                )
            self.check_link_predicate(predicate)
            if not link.get("target"):
                raise VocabularyViolation(
                    f"link with predicate '{predicate}' is missing a target; "
                    "constraint 'links require a non-empty target' was violated"
                )


def config_dir() -> Path:
    d = os.environ.get("HERDR_PLUGIN_CONFIG_DIR")
    if d:
        return Path(d)
    return Path.home() / ".config" / "herdr" / "plugins" / PLUGIN_ID


def legacy_config_dir() -> Path:
    """The pre-rename per-id config dir, a sibling of the current one.

    herdr names each plugin's config dir by its plugin id, so the id rename
    moved the directory: the legacy dir sits next to the new one under the
    same parent (whether that parent is ~/.config/herdr/plugins or whatever
    HERDR_PLUGIN_CONFIG_DIR points at).
    """
    return config_dir().parent / LEGACY_PLUGIN_ID


def vocabulary_path() -> Path:
    """Locate tbox.toml, falling back to a legacy haikei.wiki config dir.

    After the id rename the config dir moved. Until the user moves their
    tbox.toml over, keep reading the legacy file and print a one-line hint
    to stderr. Never copy or delete the user's files: migration is a human
    decision (README, 'Migrating from haikei.wiki').
    """
    tbox = config_dir() / "tbox.toml"
    if tbox.exists():
        return tbox
    legacy = legacy_config_dir() / "tbox.toml"
    if legacy.exists():
        print(
            f"{PLUGIN_ID}: no tbox.toml in this config dir; using the legacy "
            f"{legacy} - move it to {tbox} (README: 'Migrating from "
            f"{LEGACY_PLUGIN_ID}')",
            file=sys.stderr,
        )
        return legacy
    return tbox


def seed_config_dir() -> Path:
    """Ensure the config dir exists and contains tbox.toml.

    Seeds the shipped starter vocabulary on first run. Never overwrites an
    existing tbox.toml - schema changes are a human decision. Skipped while
    a legacy haikei.wiki vocabulary exists: seeding a fresh starter here
    would shadow the user's customized legacy file.
    """
    d = config_dir()
    d.mkdir(parents=True, exist_ok=True)
    tbox = d / "tbox.toml"
    if not tbox.exists() and not (legacy_config_dir() / "tbox.toml").exists():
        shutil.copyfile(STARTER_TBOX, tbox)
    return d


def load_vocabulary(path: Path | None = None) -> Vocabulary:
    if path is None:
        seed_config_dir()
        path = vocabulary_path()
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"capture vocabulary not found: {path}")
    with open(path, "rb") as f:
        data = tomllib.load(f)
    entity_types = frozenset(data.get("entity_types", {}))
    link_predicates = frozenset(data.get("link_predicates", {}))
    if not entity_types or not link_predicates:
        raise ValueError(
            f"vocabulary file {path} must define non-empty [entity_types] "
            "and [link_predicates] tables"
        )
    return Vocabulary(entity_types=entity_types, link_predicates=link_predicates)
