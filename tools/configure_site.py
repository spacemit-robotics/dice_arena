# Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
# SPDX-License-Identifier: Apache-2.0
"""Create a new site config from reviewed algorithm resources; never connect hardware."""

import argparse
import errno
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys


def hand_positions(targets_0_100):
    """Algorithm recipes use the hand's scale (0 open, 100 closed); the framework 0 closed, 1
    open."""
    return [round(1 - value / 100, 4) for value in targets_0_100]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "prefix",
        "device_plan",
        "source_root",
        "green_config",
        "runtime_directory",
        "output",
    ):
        parser.add_argument(name)
    args = parser.parse_args()
    destination = Path(args.output).absolute()
    if os.path.lexists(destination):
        raise FileExistsError(errno.EEXIST, "configuration already exists", str(destination))
    destination = destination.resolve()
    prefix = Path(args.prefix).resolve()
    layout = json.loads((prefix / ".spacemit-manipulation.json").read_text())
    source, runtime = Path(args.source_root).resolve(), Path(args.runtime_directory).resolve()
    plan, config = Path(args.device_plan).resolve(), Path(args.green_config).resolve()
    sys.path.insert(0, str(source))
    pipeline = importlib.import_module("cup_grasp_demo.flow.green_pipeline")
    if not Path(pipeline.__file__).resolve().is_relative_to(source):
        raise RuntimeError("conflicting algorithm source")
    cfg = pipeline.load_config(config)
    green = pipeline.validate(cfg)
    subprocess.run(
        [str(prefix / layout["bindir"] / "manipulation-device"), "validate", str(plan)], check=True
    )
    gestures = json.loads((source / "configs/actions/gestures/result_feedback.json").read_text())[
        "gestures"
    ]

    def relative(path):
        return os.path.relpath(path, destination.parent)

    output = dict(
        schema_version=2,
        executable=relative(prefix / layout["bindir"] / "manipulation-device"),
        device_plan=relative(plan),
        policy_library=relative(prefix / layout["libdir"] / "libcup_task.so"),
        grip_ack_directory=relative(runtime / "grip_ack"),
        # speed_scale applies to fixture planners only; the green planner uses the FAST phase
        # speeds.
        speed_scale=0.05,
        duration_s=green.get("fast_finger_duration_s", green.get("finger_duration_s", 0.5)),
        open_positions=hand_positions(green["open_targets_0_100"]),
        grip_positions=hand_positions(green["grip_targets_0_100"]),
        planner=dict(
            type="green_cup",
            source_root=relative(source),
            config=relative(config),
            session_directory=relative(runtime / "sessions"),
        ),
        gestures={
            name: hand_positions(gestures[old]["hand_0_100"])
            for name, old in (("win", "yeah"), ("lose", "thumbs-up"), ("draw", "tie"))
        },
    )
    with destination.open("x", encoding="utf-8") as stream:
        json.dump(output, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(
        "configuration created; no motion performed; review the hand targets for this installation"
    )


if __name__ == "__main__":
    try:
        main()
    except FileExistsError as error:
        print(
            f"configuration already exists; existing file kept: {error.filename}", file=sys.stderr
        )
        raise SystemExit(1) from None
