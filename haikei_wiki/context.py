"""Parse HERDR_PLUGIN_CONTEXT_JSON into provenance fields.

Field names verified against the real context JSON dumped in a live Herdr
pane (see ACCEPTANCE.md, item 3):

    workspace_id, workspace_label, workspace_cwd,
    tab_id, tab_label,
    focused_pane_id, focused_pane_cwd, focused_pane_agent,
    focused_pane_status,
    invocation_source, correlation_id,
    selected_text (only when text is selected),
    clicked_url / link_handler_id (link-handler invocations only)

The context JSON carries no worktree field. Worktree provenance is resolved
by calling `herdr worktree list --workspace <id>` through $HERDR_BIN_PATH
and matching the entry whose open_workspace_id equals the workspace id.
"""

import json
import os
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class Provenance:
    agent: Optional[str] = None
    worktree: Optional[str] = None
    worktree_branch: Optional[str] = None
    worktree_repo_root: Optional[str] = None
    workspace: Optional[str] = None
    workspace_label: Optional[str] = None
    workspace_cwd: Optional[str] = None
    tab: Optional[str] = None
    pane: Optional[str] = None
    selected_text: Optional[str] = None
    raw: Optional[dict] = None

    def as_dict(self) -> dict:
        d = {
            "agent": self.agent,
            "worktree": self.worktree,
            "worktree_branch": self.worktree_branch,
            "worktree_repo_root": self.worktree_repo_root,
            "workspace": self.workspace,
            "workspace_label": self.workspace_label,
            "workspace_cwd": self.workspace_cwd,
            "tab": self.tab,
            "pane": self.pane,
        }
        if self.selected_text is not None:
            d["selected_text"] = self.selected_text
        return {k: v for k, v in d.items() if v is not None}


def load_context() -> dict:
    raw = os.environ.get("HERDR_PLUGIN_CONTEXT_JSON", "")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def parse_provenance(context: Optional[dict] = None) -> Provenance:
    if context is None:
        context = load_context()

    def s(key: str) -> Optional[str]:
        v = context.get(key)
        return str(v) if v is not None else None

    return Provenance(
        agent=s("focused_pane_agent"),
        workspace=s("workspace_id"),
        workspace_label=s("workspace_label"),
        workspace_cwd=s("workspace_cwd"),
        tab=s("tab_id"),
        pane=s("focused_pane_id"),
        selected_text=s("selected_text"),
        raw=context,
    )


def resolve_worktree(prov: Provenance) -> Provenance:
    """Fill in worktree provenance via `herdr worktree list --workspace <id>`."""
    if not prov.workspace:
        return prov
    try:
        from .herdr import run

        result = run(["worktree", "list", "--workspace", prov.workspace])
    except Exception:
        return prov
    for wt in result.get("worktrees", []):
        if wt.get("open_workspace_id") == prov.workspace:
            prov.worktree = wt.get("path")
            prov.worktree_branch = wt.get("branch")
            prov.worktree_repo_root = (result.get("source") or {}).get("repo_root")
            break
    return prov
