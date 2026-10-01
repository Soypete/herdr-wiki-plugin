"""Verify the herdr-orchestrator skill copies are byte-identical across all three harness directories."""

import filecmp
import os
import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SKILL_SUBDIRS = [
    "skills/claude/herdr-orchestrator",
    "skills/codex/plugins/herdr-wiki/skills/herdr-orchestrator",
    ".opencode/skills/herdr-orchestrator",
]


def _walk_relative(basedir):
    for root, dirs, files in os.walk(basedir):
        for f in files:
            yield os.path.relpath(os.path.join(root, f), basedir)


def test_all_copies_have_same_files():
    dirs = [os.path.join(REPO_ROOT, s) for s in SKILL_SUBDIRS]
    file_sets = [set(_walk_relative(d)) for d in dirs]
    reference = file_sets[0]
    for s, fs in zip(SKILL_SUBDIRS[1:], file_sets[1:]):
        assert fs == reference, (
            f"{s} has different files: +{fs - reference}, -{reference - fs}"
        )


def test_all_copies_are_byte_identical():
    dirs = [os.path.join(REPO_ROOT, s) for s in SKILL_SUBDIRS]
    reference_files = list(_walk_relative(dirs[0]))
    for f in reference_files:
        paths = [os.path.join(d, f) for d in dirs]
        assert all(os.path.exists(p) for p in paths), f"Missing {f} in one copy"
        for p in paths[1:]:
            assert filecmp.cmp(paths[0], p, shallow=False), (
                f"{f} differs between {SKILL_SUBDIRS[0]} and {[d for d, p_ in zip(SKILL_SUBDIRS[1:], [p])][0]}"
            )
