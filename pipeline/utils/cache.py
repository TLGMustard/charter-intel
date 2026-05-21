"""
pipeline/utils/cache.py
Cache manager for the charter intelligence pipeline.

Implements a three-tier cache:
  - state/    — quarterly refresh
  - community/ — quarterly refresh
  - synthesis/ — per-run, invalidated on community cache update

Keys are file paths under data/cache/{tier}/{state}/{community_id}/{stage}_{date}.json
Cache reads return the most recent matching file; writes create new dated files.
"""
from __future__ import annotations
import json
import os
import glob
from typing import Optional

from pipeline import PipelineConfig


class CacheManager:
    def __init__(self, config: PipelineConfig):
        self.enabled = config.cache_enabled
        self.force_refresh = config.force_refresh
        self.base = "data/cache"

    def get(self, key: str) -> Optional[dict]:
        """Return cached value for key, or None if not found / disabled."""
        if not self.enabled or self.force_refresh:
            return None
        path = os.path.join(self.base, key)
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f)
        return None

    def set(self, key: str, value: dict) -> None:
        """Write value to cache at key."""
        if not self.enabled:
            return
        path = os.path.join(self.base, key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(value, f, indent=2)

    def invalidate(self, prefix: str) -> int:
        """Delete all cache files matching prefix. Returns count deleted."""
        pattern = os.path.join(self.base, prefix, "**", "*.json")
        files = glob.glob(pattern, recursive=True)
        for f in files:
            os.remove(f)
        return len(files)
