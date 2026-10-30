# Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
# SPDX-License-Identifier: Apache-2.0
"""Dice Arena game commands. The game, its models and the video server are installed with the SDK."""

import getpass
import json
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
from urllib.parse import quote
from urllib.request import urlopen
from spacemit_manipulation.operator_support import Context, argument_parser, run
from cup_shake.operator import CUP_COMMANDS, add_commands, execute as execute_cup

VIDEO_PORTS = (8554, 8889)  # RTSP from the dice recognition, WebRTC to the browser (mediamtx.yml).
TTS_PORT = 18082  # Local MOSS-TTS daemon (game/backend/components/tts_moss_nano/config.json).


def port_in_use(port):
    with socket.socket() as probe:
        probe.settimeout(0.2)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def own_tts_daemon(runtime, game):
    """The TTS daemon a previous serve left running (it is reused, as the original game does)."""
    try:
        pid = int((runtime / f"moss-tts-{TTS_PORT}.pid").read_text().strip())
        return str(game) in Path(f"/proc/{pid}/cmdline").read_bytes().decode(errors="replace")
    except (OSError, ValueError):
        return False


def serve(context, args):
    game = context.data("dice_arena") / "game"
    application = context.local("cup_application.json")
    if not application.is_file():
        raise FileNotFoundError(f"{application} not found; generate it with `dice-arena configure`")
    if not (game / "vision/yolov8_objdetect/bin/yolov8_camera").is_file():
        raise FileNotFoundError("dice recognition (yolov8_camera) is not built; build dice_arena with mm on the K3")
    if not (context.data("dice_arena") / "mediamtx/mediamtx").is_file():
        raise FileNotFoundError("MediaMTX runtime resource is missing; prepare the files in runtime_assets.json")
    # TTS daemon pid/log and other runtime files stay in the site, out of the installation.
    runtime = context.local("dice_arena")
    runtime.mkdir(parents=True, exist_ok=True)
    busy = [port for port in (*VIDEO_PORTS, args.port) if port_in_use(port)]
    if busy:
        raise RuntimeError(
            f"ports {busy} are in use: stop the other game or video service first "
            "(a former mediamtx user service: systemctl --user disable --now mediamtx)"
        )
    if port_in_use(TTS_PORT) and not own_tts_daemon(runtime, game):
        raise RuntimeError(f"port {TTS_PORT} is held by another MOSS-TTS daemon (another installation); stop it first")
    # The operator's game configuration lives in the site, created from the installed default once,
    # so reinstalling keeps it (the game reloads it on change).
    config = runtime / "config.json"
    if not config.exists():
        shutil.copyfile(game / "backend/config.json", config)
    print(f"game configuration: {config}", flush=True)
    environment = context.environment()
    environment.update(
        SPACEMIT_CUP_APPLICATION=str(application), DICE_RUNTIME_DIR=str(runtime), DICE_ARENA_CONFIG=str(config)
    )
    mediamtx = context.data("dice_arena") / "mediamtx"
    with (runtime / "mediamtx.log").open("ab") as log:
        video = subprocess.Popen(
            [str(mediamtx / "mediamtx"), str(mediamtx / "mediamtx.yml")],
            cwd=runtime,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    try:
        # The voice before the game, as the original start script did: every TTS provider the game
        # references is started (the local MOSS-TTS daemon loads its models, then stays running for the
        # next serve); remote-only ones have nothing to start. One that fails leaves a warning.
        control = [sys.executable, str(game / "backend/componentctl.py"), "--game", "dice"]
        referenced = subprocess.run(
            control + ["referenced", "tts"], cwd=game, env=environment, capture_output=True, text=True, check=False
        )
        for provider in referenced.stdout.split():
            if subprocess.run(control + ["start", provider], cwd=game, env=environment, check=False).returncode:
                print(f"warning: TTS provider {provider} is unavailable", file=sys.stderr, flush=True)
        server = subprocess.Popen(
            [sys.executable, str(game / "backend/server.py"), "--host", args.host, "--port", str(args.port)],
            cwd=game,
            env=environment,
        )
        # Ctrl+C reaches the game server directly (same process group); a stop request is forwarded.
        signal.signal(signal.SIGTERM, lambda *_: server.send_signal(signal.SIGTERM))
        while True:
            try:
                return server.wait()
            except KeyboardInterrupt:
                continue
    finally:
        video.terminate()
        try:
            video.wait(timeout=5)
        except subprocess.TimeoutExpired:
            video.kill()


def main():
    parser = argument_parser(__doc__)
    parser.add_argument("--source", help="grasp algorithm root (default: installed application resources)")
    commands = parser.add_subparsers(dest="operation", required=True)
    serve_command = commands.add_parser("serve", help="start the video server and the game; Ctrl+C stops both")
    serve_command.add_argument(
        "--host", default="0.0.0.0", help="listen address (default: every interface, as the original)"
    )
    serve_command.add_argument("--port", type=int, default=8080)
    for name in ("status", "events"):
        command = commands.add_parser(name)
        command.add_argument("--url", default="http://127.0.0.1:8080")
        if name == "events":
            command.add_argument("round_id")
    ack = commands.add_parser("ack-grip", help="publish only the current operation human grip declaration")
    ack.add_argument("token")
    ack.add_argument("output")
    ack.add_argument(
        "--operator",
        default=getpass.getuser(),
        help="name recorded with the grip confirmation (default: the login user)",
    )
    commands.add_parser("check", help="exercise the game's robot provider with the Mock cup application")
    add_commands(commands)
    args = parser.parse_args()
    context = Context(args)
    if args.operation in CUP_COMMANDS:
        execute_cup(context, args)
        return 0
    if args.operation == "serve":
        return serve(context, args)
    if args.operation in ("status", "events"):
        suffix = (
            "/api/health"
            if args.operation == "status"
            else ("/api/game/rounds/" + quote(args.round_id, safe="") + "/stream")
        )
        with urlopen(args.url.rstrip("/") + suffix, timeout=30) as response:
            if args.operation == "status":
                print(json.dumps(json.load(response), ensure_ascii=False, indent=2))
            else:
                for line in response:
                    print(line.decode("utf-8"), end="", flush=True)
    elif args.operation == "ack-grip":
        context.module(
            "spacemit_manipulation.workbench", "ack-grip", args.token, args.output, "--operator", args.operator
        )
    else:
        context.script(
            context.data("dice_arena") / "tests/check_game.py",
            context.data("dice_arena") / "game",
            context.data("dice_arena") / "config/mock.json",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(run(main))
