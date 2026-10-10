"""Verify the multi-file skill copies are byte-identical across all three harness directories."""

import filecmp
import os
import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
HARNESS_DIRS = [
    "skills/claude",
    "skills/codex/plugins/herdr-wiki/skills",
    ".opencode/skills",
]
SKILLS = ["herdr-orchestrator", "worker-git-identity"]


def _subdirs(skill):
    return [f"{h}/{skill}" for h in HARNESS_DIRS]


def _walk_relative(basedir):
    for root, dirs, files in os.walk(basedir):
        for f in files:
            yield os.path.relpath(os.path.join(root, f), basedir)


@pytest.mark.parametrize("skill", SKILLS)
def test_all_copies_have_same_files(skill):
    subdirs = _subdirs(skill)
    dirs = [os.path.join(REPO_ROOT, s) for s in subdirs]
    file_sets = [set(_walk_relative(d)) for d in dirs]
    reference = file_sets[0]
    for s, fs in zip(subdirs[1:], file_sets[1:]):
        assert fs == reference, (
            f"{s} has different files: +{fs - reference}, -{reference - fs}"
        )


@pytest.mark.parametrize("skill", SKILLS)
def test_all_copies_are_byte_identical(skill):
    subdirs = _subdirs(skill)
    dirs = [os.path.join(REPO_ROOT, s) for s in subdirs]
    reference_files = list(_walk_relative(dirs[0]))
    for f in reference_files:
        paths = [os.path.join(d, f) for d in dirs]
        assert all(os.path.exists(p) for p in paths), f"Missing {f} in one copy"
        for p in paths[1:]:
            assert filecmp.cmp(paths[0], p, shallow=False), (
                f"{f} differs between {subdirs[0]} and {[d for d, p_ in zip(subdirs[1:], [p])][0]}"
            )
