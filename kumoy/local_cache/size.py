"""Shared helpers for cache-size computation.

Return-value contract (common to map/raster/vector): always an int >= 0.
Sizes are display-only, so anything unreadable counts as 0 — a missing
file as well as a failed stat (e.g. deleted mid-scan, or locked by
another process on Windows). Directory-level failures (scandir etc.)
propagate so the caller (UI) can fall back to a "size unknown" label.
"""

import os
from typing import Iterable


def files_total_size(paths: Iterable[str]) -> int:
    """Return the total size of the given paths, counting unreadable ones as 0."""
    total = 0
    for path in paths:
        try:
            total += os.path.getsize(path)
        except OSError:
            # Missing or stat-failed file counts as 0 per the module contract.
            continue
    return total


def dir_total_size(cache_dir: str) -> int:
    """Return the total size of all files directly under the directory."""
    total = 0
    for entry in os.scandir(cache_dir):
        try:
            if not entry.is_file():
                continue
            total += entry.stat().st_size
        except OSError:
            # Vanished or stat-failed entry counts as 0 per the module contract.
            continue
    return total
