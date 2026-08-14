"""Shared helpers for cache-size computation.

Return-value contract (common to map/raster/vector):
  - None … no target file exists (not cached)
  - >= 0 … files exist; 0 means an empty file. Keeping existence
           distinct from size keeps an empty cache clearable.
Sizes are display-only, so a failed stat on an individual file counts
as 0. Directory-level failures (scandir etc.) propagate so the caller
(UI) can fall back.
"""

import os
from typing import Iterable, Optional


def files_total_size(paths: Iterable[str]) -> Optional[int]:
    """Return the total size of the given paths, ignoring nonexistent ones."""
    total = None
    for path in paths:
        if not os.path.exists(path):
            continue
        total = total or 0
        try:
            total += os.path.getsize(path)
        except OSError:
            pass
    return total


def dir_total_size(cache_dir: str) -> Optional[int]:
    """Return the total size of all files directly under the directory."""
    total = None
    for entry in os.scandir(cache_dir):
        try:
            if not entry.is_file():
                continue
            size = entry.stat().st_size
        except OSError:
            size = 0
        total = (total or 0) + size
    return total
