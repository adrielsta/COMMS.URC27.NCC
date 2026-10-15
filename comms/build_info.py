"""Identify the checkout used to start a mission-control server."""
from pathlib import Path
import re
import subprocess


VERSION = "0.2.0"
ROOT = Path(__file__).resolve().parents[1]


def get_build_info():
    """Read local Git metadata once at server startup, with an archive fallback."""
    result = {"name": "NCC Mission Control", "version": VERSION,
              "commit": "source archive", "dirty": False}
    try:
        revision = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "--short=12", "HEAD"],
            capture_output=True, text=True, timeout=2, check=False,
        )
        commit = revision.stdout.strip()
        if revision.returncode == 0 and re.fullmatch(r"[0-9a-f]{12,40}", commit):
            result["commit"] = commit
            changed = subprocess.run(
                ["git", "-C", str(ROOT), "diff", "--quiet", "HEAD", "--"],
                capture_output=True, timeout=2, check=False,
            )
            result["dirty"] = changed.returncode == 1
    except (OSError, subprocess.TimeoutExpired):
        pass
    return result
