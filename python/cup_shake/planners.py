# Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
# SPDX-License-Identifier: Apache-2.0
"""Application-local planning ports; fixture is never accepted for physical drivers."""

import hashlib
from pathlib import Path


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
        return LegacyGreenPlanner(resolved, state)
    raise ValueError("unknown planner registration: " + kind)
