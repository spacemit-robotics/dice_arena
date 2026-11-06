# Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
# SPDX-License-Identifier: Apache-2.0
"""Exercise the installed game's registry and robot provider with the Mock cup application; no
hardware."""

import argparse
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
from check_runtime import check as check_runtime


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("game")
    parser.add_argument("application_config")
    args = parser.parse_args()
    game = Path(args.game).resolve()
    check_runtime(game)
    os.environ["SPACEMIT_CUP_APPLICATION"] = str(Path(args.application_config).resolve())
    sys.path.insert(0, str(game / "backend"))
    from core.components import build_registry
    from core.robot import RobotProvider
    from core.state_schema import StateMachineError, validate_state_machine

    config = json.loads((game / "backend/config.json").read_text())
    assert config["providers"]["robot_arm"] == "robot_arm_spacemit"
    assert "robot_home_patrol" not in config and "asr" not in config["providers"]
    assert (
        not (game / "backend/components/robot_arm_nero").exists()
        and not (game / "backend/games/rps").exists()
    )
    # `dice-arena serve` starts the voice the game references, local MOSS-TTS first (start_web.sh).
    referenced = subprocess.run(
        [
            sys.executable,
            str(game / "backend/componentctl.py"),
            "--game",
            "dice",
            "referenced",
            "tts",
        ],
        cwd=game,
        capture_output=True,
        text=True,
        check=True,
    )
    assert referenced.stdout.split()[0] == "tts_moss_nano", referenced.stdout
    # The manifest validator refuses what the game would not run as written: a robot timeout the
    # provider rejects, and transition actions other than plain speech.
    machine = json.loads((game / "backend/games/dice/manifest.json").read_text())["state_machine"]
    validate_state_machine(machine, "dice")
    for state, field, value in (
        ("game_start", "on_enter", dict(action="robot", command="grasp_cup", timeout_seconds=181)),
        ("rules", "repeat", dict(action="robot", command="reset_home")),
        ("rules", "repeat", {"action": "speech", "text": "规则", "await": True}),
    ):
        changed = copy.deepcopy(machine)
        if field == "on_enter":
            changed["states"][state]["on_enter"][0] = value
        else:
            changed["states"][state]["on_intent"][field]["actions"] = [value]
        try:
            validate_state_machine(changed, "dice")
        except StateMachineError:
            continue
        raise AssertionError(f"invalid state machine accepted: {value}")
    registry = build_registry(log=False)
    provider = registry.require("robot_arm_spacemit", expected_type="robot")
    assert isinstance(provider, RobotProvider)
    assert provider.home_on_boot is False
    assert provider.app.client is None
    events = []
    kwargs = dict(on_event=events.append, is_cancelled=lambda: False)
    try:
        provider.ensure_started()  # Game entry: connects in the background, without motion.
        assert provider._lock.acquire(timeout=30)
        provider._lock.release()
        assert provider.app.client is not None and not events
        assert provider.reset_home(**kwargs)["at_home"]
        for name in ("grasp_cup", "shake_dice", "settle_dice"):
            result = getattr(provider, name)(**kwargs)
            assert result["status"] == "completed", result
        assert provider.feedback("win", **kwargs)["status"] == "completed"
        assert provider.ensure_home(**kwargs)["at_home"]
        provider.app.policy.step("failure", 2)
        assert provider.grasp_cup(**kwargs)["status"] == "failed"
        assert provider.app.policy.state == "fault"
    finally:
        provider.shutdown()
    print(
        json.dumps(
            dict(
                provider_contract="passed",
                mock_cycle="passed",
                fault_latch="passed",
                events=len(events),
            )
        )
    )


if __name__ == "__main__":
    main()
