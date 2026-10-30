from unittest.mock import Mock

import pytest

from calibration.web import hand_home
from calibration.web.common import read, write

READY = {"enabled": True, "fault": False, "moving": False, "position_mode": True}


@pytest.mark.parametrize("mode", ["unverified", "measured", "moving", "fault", "cancel", "send_error"])
def test_zero_command_through_framework(tmp_path, monkeypatch, mode):
    clock = [100.0]
    monkeypatch.setattr(hand_home.time, "time", lambda: clock[0])
    sent = []

    def move_hand(positions, duration_s):
        if mode == "send_error":
            raise RuntimeError("灵巧手指令未完成：stop_unknown")
        if mode == "cancel":
            raise KeyboardInterrupt
        sent.append((positions, duration_s))
        clock[0] += duration_s
        return {"status": "succeeded" if mode == "measured" else "unverified"}

    arm = Mock()
    arm.move_hand.side_effect = move_hand
    arm.state.side_effect = lambda: dict(READY, fault=mode == "fault" and bool(sent))
    arm.read_joints.side_effect = lambda: {"joints_rad": [0.1 if mode == "moving" and sent else 0.0] * 7}
    if mode in ("unverified", "measured"):
        proof = hand_home.reset_hand(arm, tmp_path)
        assert proof["command_sent"] and proof["status"] == "completed"
        assert proof["confirmed"] is (mode == "measured")
        assert proof["verification"] == ("position_feedback" if mode == "measured" else "command_only")
        assert proof["completed_at"] - proof["commanded_at"] >= 1.0
    else:
        with pytest.raises(KeyboardInterrupt if mode == "cancel" else RuntimeError):
            hand_home.reset_hand(arm, tmp_path)
        assert read(tmp_path / "hand_home.json")["status"] == "failed"
        assert read(tmp_path / "hand_home.json")["confirmed"] is False
    if mode not in ("cancel", "send_error"):
        assert sent == [([0.0] * 6, 1.0)]
    arm.move.assert_not_called()


def test_hand_is_not_commanded_while_the_arm_is_moving(tmp_path):
    arm = Mock()
    arm.state.return_value = dict(READY, moving=True)
    arm.read_joints.return_value = {"joints_rad": [0.0] * 7}
    with pytest.raises(RuntimeError, match="控制状态异常"):
        hand_home.reset_hand(arm, tmp_path)
    arm.move_hand.assert_not_called()
    assert read(tmp_path / "hand_home.json")["command_sent"] is False


def test_arm_home_cannot_clear_pending_hand_check(tmp_path):
    import time
    from calibration.web.worker import reconcile_home, BrowserWorkflow
    from calibration.web.common import CONFIG, ROOT
    from home_start import load_home

    job = tmp_path / "job"
    job.mkdir()
    config = read(CONFIG)
    config["state_file"] = str(tmp_path / "state.json")
    write(job / "config.json", config)
    write(job / "request.json", {"action": "home"})
    write(config["state_file"], {"hand_home_required": True, "home_required": True})
    reconcile_home(
        job,
        config,
        dict(
            confirmed=True,
            observed_at=time.time(),
            sdk_timestamp=time.time(),
            stationary_window_s=0.6,
            joints_rad=load_home(ROOT / config["home"]),
        ),
    )
    assert read(config["state_file"])["home_required"] is True
    flow = BrowserWorkflow(job)
    flow.save(home_required=False)
    assert read(config["state_file"])["home_required"] is True
    state = read(config["state_file"])
    state.update(
        hand_home_required=False, hand_home={"confirmed": False, "command_sent": True, "verification": "command_only"}
    )
    write(config["state_file"], state)
    flow.save(home_required=False)
    assert read(config["state_file"])["home_required"] is False
    assert read(config["state_file"])["hand_home"] == {
        "confirmed": False,
        "command_sent": True,
        "verification": "command_only",
    }


@pytest.mark.parametrize("action", ["auto", "home", "restore", "inspect"])
def test_home_adapter_changes_only_web_motion_actions(tmp_path, monkeypatch, action):
    import home_start
    import sensors
    import calibrate
    import auto_collect
    import preview
    from calibration.web.worker import install_adapters

    for obj, name in (
        (sensors, "RealSenseCamera"),
        (sensors, "NeroFeedback"),
        (calibrate, "capture_sample"),
        (auto_collect, "capture_sample"),
        (auto_collect, "AutoCollectionView"),
        (auto_collect, "ensure_can_control"),
        (preview, "CollectionPreview"),
    ):
        monkeypatch.setattr(obj, name, getattr(obj, name))
    order = []
    original = Mock(side_effect=lambda *a, **k: order.append("arm") or [0] * 7)
    monkeypatch.setattr(home_start, "move_home", original)
    reset = Mock(
        side_effect=lambda *a: (
            order.append("hand") or {"confirmed": False, "command_sent": True, "verification": "command_only"}
        )
    )
    monkeypatch.setattr(hand_home, "reset_hand", reset)
    state = tmp_path / "state.json"
    install_adapters(tmp_path, {"action": action}, {"state_file": str(state)})
    arm = Mock()
    assert home_start.move_home(arm, [], 4, 6) == [0] * 7
    assert order == (["arm"] if action == "inspect" else ["arm", "hand"])
    if action != "inspect":
        assert read(state)["hand_home_required"] is False
        reset.side_effect = RuntimeError("hand timeout")
        with pytest.raises(RuntimeError, match="hand timeout"):
            home_start.move_home(arm, [], 4, 6)
        assert read(state)["home_required"] is True
        assert read(state)["hand_home_required"] is True
