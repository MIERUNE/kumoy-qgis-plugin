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
    """Return the total size of all files under the directory, recursively.

    Recursive scandir instead of os.walk: os.walk swallows scandir errors by
    default, which would break the OSError contract above.
    """
    total = 0
    for entry in os.scandir(cache_dir):
        # follow_symlinks=False so a symlink cycle cannot recurse forever.
        if entry.is_dir(follow_symlinks=False):
            total += dir_total_size(entry.path)
        elif entry.is_file():
            total += entry.stat().st_size
    return total
