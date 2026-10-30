# Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
# SPDX-License-Identifier: Apache-2.0
"""Offline compatibility check against the actual upstream algorithms; no camera/CAN creation."""

import argparse
import json
from pathlib import Path
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root")
    parser.add_argument("--config", type=Path, help="site configuration with registered calibration and table")
    args = parser.parse_args()
    from cup_shake.legacy_green import LegacyGreenPlanner
    from spacemit_manipulation.urdf_fk import UrdfKinematics

    source = Path(args.source_root).resolve()
    with tempfile.TemporaryDirectory(prefix="planning-port-") as temporary:
        configuration = args.config.resolve() if args.config else source / "configs/green_cup.json"
        config = dict(source_root=str(source), config=str(configuration), session_directory=temporary)
        planner = LegacyGreenPlanner(config, lambda: dict(joints_rad=[0] * 7))
        try:
            if "pyAgxArm" in sys.modules or planner.workflow._vision is not None:
                raise RuntimeError("offline planner initialization created a hardware dependency")
            old = planner.workflow.kin.model
            model = UrdfKinematics(
                source / "nero_revo2_control/models/hand_geometry/nero/urdf/nero_description.urdf",
                "base_link",
                "link7",
                [f"joint{i}" for i in range(1, 8)],
            )
            maximum = 0
            for index in range(11):
                joints = [low + (high - low) * (0.25 + 0.05 * index) for low, high in old.limits_rad]
                actual = model.forward(joints)
                expected = [value for row in old.fk(joints) for value in row]
                maximum = max(maximum, max(abs(a - b) for a, b in zip(actual, expected)))
            if maximum > 1e-10:
                raise RuntimeError("URDF FK disagrees with upstream: " + str(maximum))
            planner.unchanged()
            print(
                json.dumps(
                    dict(
                        initialization="passed",
                        pinned_resources=len(planner.fingerprints),
                        sdk_imported=False,
                        camera_started=False,
                        fk_max_entry_error=maximum,
                    )
                )
            )
        finally:
            planner.close()


if __name__ == "__main__":
    main()
