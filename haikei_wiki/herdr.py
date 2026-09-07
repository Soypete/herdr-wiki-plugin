"""Call back into Herdr via $HERDR_BIN_PATH (never bare `herdr`)."""

import json
import os
import subprocess
from typing import Optional


class HerdrError(RuntimeError):
    pass


def herdr_bin() -> str:
    return os.environ.get("HERDR_BIN_PATH") or "herdr"


def run(args: list[str], timeout: float = 30.0) -> dict:
    """Run a herdr CLI command (argv, no shell) and parse the JSON response."""
    cmd = [herdr_bin(), *args]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    out = proc.stdout.strip()
    data: Optional[dict] = None
    if out:
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            data = None
    if proc.returncode != 0:
        detail = (
            (data or {}).get("error", {}).get("message", proc.stderr.strip() or out)
        )
        raise HerdrError(f"herdr {' '.join(args)} failed ({proc.returncode}): {detail}")
    if isinstance(data, dict) and isinstance(data.get("result"), dict):
        return data["result"]
    return data or {}
