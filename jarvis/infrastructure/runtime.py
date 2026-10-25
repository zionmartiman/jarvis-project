"""Location of the per-user runtime directory used for sockets and locks."""

from __future__ import annotations

import os
from pathlib import Path

_FALLBACK_UID = 1000


def runtime_dir() -> Path:
    """Return /run/user/<uid>; hosts without os.getuid (Windows) use uid 1000."""
    uid = int(os.getuid()) if hasattr(os, "getuid") else _FALLBACK_UID
    return Path("/run/user") / str(uid)
