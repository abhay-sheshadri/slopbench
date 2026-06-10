#!/usr/bin/env python3
"""Merge per-segment file_cache_dir copies into a single run-root cache.

Companion to the abhay-pi run-loop change that shares ./file_cache_dir across
phase segments via a symlink instead of copying it forward. For each run dir
under outputs/03_run_agents this:

  1. moves the segment cache with the most entries to <run>/file_cache_dir
     (cheap rename; in practice the biggest cache is a superset of the others),
  2. hardlink-merges the remaining segment caches into it (entries are
     content-addressed and immutable, so name collisions are identical files),
  3. replaces every segment cache dir with a symlink to ../file_cache_dir.

Refuses to touch runs that look live (.pi_transcripts/RUNNING marker).
"""

import os
import shutil
import sys
from pathlib import Path

RUNS_ROOT = Path(__file__).resolve().parent.parent / "outputs" / "03_run_agents"
RUNNING_MARKER = ".pi_transcripts/RUNNING"
CACHE_NAME = "file_cache_dir"


def merge_into(seg_cache: Path, root_cache: Path) -> tuple[int, int]:
    linked = skipped = 0
    for entry in os.scandir(seg_cache):
        assert entry.is_file(follow_symlinks=False), f"unexpected non-file {entry.path}"
        try:
            os.link(entry.path, root_cache / entry.name)
            linked += 1
        except FileExistsError:
            skipped += 1
    return linked, skipped


def migrate_run(run_dir: Path) -> None:
    seg_caches = sorted(
        p / CACHE_NAME
        for p in run_dir.iterdir()
        if p.is_dir()
        and p.name.startswith("phase_segment_")
        and (p / CACHE_NAME).is_dir()
    )
    seg_caches = [c for c in seg_caches if not c.is_symlink()]
    if not seg_caches:
        return
    assert not (
        run_dir / RUNNING_MARKER
    ).exists(), f"{run_dir.name} looks live, aborting"

    root_cache = run_dir / CACHE_NAME
    if not root_cache.exists():
        biggest = max(seg_caches, key=lambda c: len(os.listdir(c)))
        print(
            f"{run_dir.name}: renaming {biggest.parent.name}/{CACHE_NAME} to run root"
        )
        os.rename(biggest, root_cache)
        os.symlink(os.path.join("..", CACHE_NAME), biggest)
        seg_caches.remove(biggest)

    for seg_cache in seg_caches:
        assert seg_cache.parent.parent == run_dir, f"unexpected nesting: {seg_cache}"
        linked, skipped = merge_into(seg_cache, root_cache)
        shutil.rmtree(seg_cache)
        os.symlink(os.path.join("..", CACHE_NAME), seg_cache)
        print(
            f"{run_dir.name}: {seg_cache.parent.name} merged "
            f"({linked} new, {skipped} duplicate) and symlinked",
            flush=True,
        )


def main() -> None:
    only = sys.argv[1] if len(sys.argv) > 1 else None
    run_dirs = sorted(
        p
        for p in RUNS_ROOT.iterdir()
        if p.is_dir() and (only is None or p.name == only)
    )
    assert run_dirs, f"no run dirs matched {only!r}"
    free_before = shutil.disk_usage(RUNS_ROOT).free
    for run_dir in run_dirs:
        migrate_run(run_dir)
    freed = shutil.disk_usage(RUNS_ROOT).free - free_before
    print(f"done; freed {freed / 1e9:.1f} GB")


if __name__ == "__main__":
    sys.exit(main())
