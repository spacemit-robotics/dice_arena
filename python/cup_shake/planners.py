# Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
# SPDX-License-Identifier: Apache-2.0
"""Application-local planning ports; fixture is never accepted for physical drivers."""

import hashlib
from pathlib import Path
import sys


class FixturePlanner:
    def __init__(self, config, _state):
        self.config = config
        self.home = config["home_rad"]

    def prepare(self):
        return None

    def targets(self, phase, _state):
        return self.config.get("targets", {}).get(phase, [])

    def close(self):
        pass

    def verify_lower(self, _state):
        return None  # Offline fixture is only constructible for mock_device.


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def preserved_legacy_resources(source_root):
    """The former share/cup_shake directory an upgrade kept in place, when a site still uses it.

    Installation never replaces an existing cup_shake directory with the dice_arena alias, so a
    configuration written before the merge keeps reading those resources and misses later updates.
    """
    for directory in (source_root, *source_root.parents):
        if directory.name == "cup_shake" and (directory.parent / "dice_arena").is_dir():
            return None if directory.is_symlink() else directory
    return None


def make_planner(config, state, driver, directory=None):
    kind = config["type"]
    if kind == "fixture":
        if driver != "mock_device":
            raise ValueError("fixture planner is forbidden for physical drivers")
        return FixturePlanner(config, state)
    if kind == "legacy_green":
        from .legacy_green import LegacyGreenPlanner

        resolved = dict(config)
        unknown = set(config) - {"type", "source_root", "config", "session_directory"}
        if unknown:  # Phase speeds, grasp and shake come from the algorithm configuration (FAST).
            raise ValueError(
                "legacy_green planner keys: type, source_root, config, session_directory; got "
                + ", ".join(sorted(unknown))
            )
        base = Path.cwd() if directory is None else Path(directory)
        for key in ("source_root", "config", "session_directory"):
            resolved[key] = str((base / config[key]).resolve())
        legacy = preserved_legacy_resources(Path(resolved["source_root"]))
        if legacy is not None:
            current = legacy.parent / "dice_arena"
            print(f"warning: planner.source_root uses {legacy}, the former resources an upgrade kept; current "
                  f"resources are in {current}. Delete {legacy} and the old cup_shake build directory, then "
                  f"reinstall; or point source_root at {current / 'algorithms'}.", file=sys.stderr, flush=True)
        return LegacyGreenPlanner(resolved, state)
    raise ValueError("unknown planner registration: " + kind)
