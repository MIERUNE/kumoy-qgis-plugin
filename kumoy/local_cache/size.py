"""Shared helpers for cache-size computation.

Pure summation only: existence checks belong to the callers. Any OSError
(e.g. a file deleted between the caller's check and the stat here, or one
locked by another process on Windows) propagates so the UI can fall back
to a "size unknown" label.
"""

import os
from collections.abc import Iterable


def files_total_size(paths: Iterable[str]) -> int:
    """Return the total size of the given files. Callers ensure they exist."""
    return sum(os.path.getsize(path) for path in paths)


def dir_total_size(cache_dir: str) -> int:
    """Return the total size of all files directly under the directory."""
    return sum(e.stat().st_size for e in os.scandir(cache_dir) if e.is_file())
