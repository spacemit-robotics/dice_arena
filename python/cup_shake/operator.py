# Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
# SPDX-License-Identifier: Apache-2.0
"""Site preparation and explicit application operations, separate from device drivers."""

from pathlib import Path


CUP_COMMANDS = ("mock", "configure", "inspect", "cycle", "home", "reset")


def add_commands(commands):
    commands.add_parser("mock", help="run the installed Mock grab/shake/place cycle; no hardware")
    commands.add_parser("configure", help="generate a new application configuration offline")
    commands.add_parser("inspect", help="connect and read; no motion")
    cycle = commands.add_parser(
        "cycle", help="execute one grab/shake/place cycle on the real device"
    )
    commands.add_parser("home", help="the arm to HOME with the hand opening")
    commands.add_parser(
        "reset",
        help="after inspecting the arm, hand and cup, forget the task state that blocks motion; "
        "no motion",
    )
    cycle.add_argument(
        "--operator", help="name recorded with the grip confirmation (default: the login user)"
    )


def execute(context, args):
    source = (
        Path(args.source).resolve() if args.source else context.data("dice_arena") / "algorithms"
    )
    if args.operation == "mock":
        context.module("cup_shake", context.data("dice_arena") / "config/mock.json", "cycle")
    elif args.operation == "configure":
        if not context.local("green_cup.json").is_file():
            raise FileNotFoundError(
                f"{context.local('green_cup.json')} not found; "
                "complete hand-eye calibration with calibrate.sh apply first"
            )
        context.script(
            context.data("dice_arena") / "tools/configure_site.py",
            context.prefix,
            context.plan_for("nero"),
            source,
            context.local("green_cup.json"),
            context.local("runtime"),
            context.local("cup_application.json"),
        )
    else:
        if not context.local("cup_application.json").is_file():
            raise FileNotFoundError(
                f"{context.local('cup_application.json')} not found; generate it with `dice-arena "
                "configure`"
            )
        arguments = [context.local("cup_application.json"), args.operation]
        if args.operation == "cycle":
            if args.operator:
                arguments += ["--operator", args.operator]
        context.module("cup_shake", *arguments)
