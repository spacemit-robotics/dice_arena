# Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
# SPDX-License-Identifier: Apache-2.0
"""Cup application commands: `inspect` only reads, `cycle` and `home` drive the device, `reset`
forgets a recorded task state without opening it."""

import argparse
import getpass
import json
from pathlib import Path
import signal
import time
from spacemit_manipulation.workbench import save_new
from .runtime import CupApplication


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config")
    parser.add_argument("command", choices=["inspect", "cycle", "home", "reset"])
    parser.add_argument(
        "--operator", help="name recorded with each grip confirmation (default: the login user)"
    )
    args = parser.parse_args()
    args.operator = (
        args.operator or getpass.getuser()
    )  # Who confirmed the grip, for the run record.
    interrupted = [False]
    signal.signal(signal.SIGINT, lambda *_args: interrupted.__setitem__(0, True))
    signal.signal(signal.SIGTERM, lambda *_args: interrupted.__setitem__(0, True))

    def event(value):
        print(json.dumps(value, ensure_ascii=False), flush=True)
        if value.get("phase") == "await_grip_confirmation" and args.operator:
            answer = input("保持安全距离检查持杯状态；确认抓稳输入 CONFIRM，其他输入终止：")
            if answer != "CONFIRM":
                interrupted[0] = True
                return
            output = Path(value["acknowledgement"])
            output.parent.mkdir(parents=True, exist_ok=True)
            save_new(
                output,
                dict(token=value["token"], operator=args.operator, checked_epoch_s=time.time()),
            )

    if args.command == "reset":  # After the operator inspected the arm, hand and cup.
        record = CupApplication(args.config, allow_motion=False).reset()
        print(
            json.dumps(dict(status="reset", removed=record), ensure_ascii=False)
            if record
            else json.dumps(dict(status="nothing recorded"))
        )
        return 0
    app = CupApplication(args.config, allow_motion=args.command != "inspect")
    try:
        app.connect(vision=args.command != "home")
        if args.command == "inspect":
            print(json.dumps(app.client.state()))
            return 0
        if args.command == "home":  # HOME with the hand opening.
            result = app.command("reset_home", on_event=event, is_cancelled=lambda: interrupted[0])
            print(json.dumps(result, ensure_ascii=False), flush=True)
            return 0 if result["status"] == "completed" else 1
        for command in ("grasp_cup", "shake_dice", "settle_dice"):
            result = app.command(command, on_event=event, is_cancelled=lambda: interrupted[0])
            print(json.dumps(result, ensure_ascii=False), flush=True)
            if result["status"] != "completed":
                return 1
        return 0
    finally:
        app.close()


if __name__ == "__main__":
    raise SystemExit(main())
