# Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
# SPDX-License-Identifier: Apache-2.0
"""Exercise the installed game's registry and robot provider with the Mock cup application; no hardware."""

import argparse
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

    config = json.loads((game / "backend/config.json").read_text())
    assert config["providers"]["robot_arm"] == "robot_arm_spacemit"
    assert config["robot_home_patrol"] is False and "asr" not in config["providers"]
    assert not (game / "backend/components/robot_arm_nero").exists() and not (game / "backend/games/rps").exists()
    # `dice-arena serve` starts the voice the game references, local MOSS-TTS first (start_web.sh).
    referenced = subprocess.run(
        [sys.executable, str(game / "backend/componentctl.py"), "--game", "dice", "referenced", "tts"],
        cwd=game,
        capture_output=True,
        text=True,
        check=True,
    )
    assert referenced.stdout.split()[0] == "tts_moss_nano", referenced.stdout
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
    print(json.dumps(dict(provider_contract="passed", mock_cycle="passed", fault_latch="passed", events=len(events))))


if __name__ == "__main__":
    main()
