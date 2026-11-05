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
    pipeline.validate(cfg)  # Refuses an invalid site configuration before anything is written.
    subprocess.run(
        [str(prefix / layout["bindir"] / "manipulation-device"), "validate", str(plan)], check=True
    )

    def relative(path):
        return os.path.relpath(path, destination.parent)

    output = dict(
        schema_version=3,
        executable=relative(prefix / layout["bindir"] / "manipulation-device"),
        device_plan=relative(plan),
        policy_library=relative(prefix / layout["libdir"] / "libcup_task.so"),
        grip_ack_directory=relative(runtime / "grip_ack"),
        # A task state that needs the operator (cup possibly held, fault) outlives the process.
        state_file=relative(runtime / "task_state.json"),
        # speed_scale applies to fixture planners only; the green planner uses the FAST phase
        # speeds.
        speed_scale=0.05,
        planner=dict(
            type="green_cup",
            source_root=relative(source),
            config=relative(config),
            session_directory=relative(runtime / "sessions"),
        ),
    )
    with destination.open("x", encoding="utf-8") as stream:
        json.dump(output, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print("configuration created; no motion performed")


if __name__ == "__main__":
    try:
        main()
    except FileExistsError as error:
        print(
            f"configuration already exists; existing file kept: {error.filename}", file=sys.stderr
        )
        raise SystemExit(1) from None
