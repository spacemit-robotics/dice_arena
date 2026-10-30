"""framework.py against a real `manipulation-device serve`: the Mock device, and the Nero driver on
the CAN-free SDK fixture (a move that never arrives, cancelled by Ctrl+C). No hardware.

Needs an installed framework: MANIPULATION_PREFIX=.../output/manipulation (skipped otherwise).
"""

import json
import os
import re
import shutil
import signal
import sys
import threading
import time
from pathlib import Path

import numpy as np
import pytest

from calibration.paths import CODE

PREFIX = os.environ.get("MANIPULATION_PREFIX")
SOURCE = CODE.parents[2] / "components/control/manipulation"
pytestmark = pytest.mark.skipif(
    not (PREFIX and (Path(PREFIX) / ".spacemit-manipulation.json").is_file()),
    reason="needs an installed framework (MANIPULATION_PREFIX)",
)
NERO_LIMITS = [
    (-2.705261, 2.705261),
    (-1.745330, 1.745330),
    (-2.757621, 2.757621),
    (-1.012291, 2.146755),
    (-2.757621, 2.757621),
    (-0.733039, 0.959932),
    (-1.570797, 1.570797),
]  # pyAgxArm preset
JOINTS = [
    {"name": f"joint{i + 1}", "minimum_rad": low, "maximum_rad": high} for i, (low, high) in enumerate(NERO_LIMITS)
]
HAND = {
    "device_id": "hand_main",
    "channels": ["thumb_tip", "thumb_base", "index_finger", "middle_finger", "ring_finger", "pinky_finger"],
    "feedback": "none",
}


@pytest.fixture
def site(tmp_path, monkeypatch):
    import framework

    monkeypatch.setenv("MANIPULATION_SITE", str(tmp_path / "site"))
    monkeypatch.setenv("MANIPULATION_LOCK_DIRECTORY", str(tmp_path / "locks"))
    (tmp_path / "site").mkdir()
    yield tmp_path / "site"
    framework.close()


def mock_device(site):
    device = {
        "driver": "mock_device",
        "model": "nero",
        "effector": HAND,
        "arm": {"device_id": "arm_main", "resource_id": "mock_calibration", "joints": JOINTS},
    }
    (site / "device.yaml").write_text(json.dumps({"schema_version": 3, "device": device, "steps": []}))


def test_vendor_sdk_cannot_be_imported_beside_the_framework():
    import framework  # noqa: F401

    with pytest.raises(ImportError, match="manipulation"):
        import pyAgxArm  # noqa: F401


def test_feedback_is_fresh_and_flange_is_urdf_fk(site):
    from sensors import NeroFeedback

    mock_device(site)
    arm = NeroFeedback("can0")
    try:
        first, second = arm.read_joints(), arm.read_joints()
        assert second["sdk_timestamp"] > first["sdk_timestamp"] and first["joints_rad"] == [0.0] * 7
        flange = arm.read()
        assert flange.shape == (4, 4) and np.allclose(flange, arm.device.flange([0.0] * 7))
        with pytest.raises(RuntimeError, match="运动权限"):
            arm.move([0.1] * 7)
    finally:
        arm.close()


def test_moves_hold_and_hand_go_through_one_session(site):
    import framework
    from sensors import NeroFeedback

    mock_device(site)
    framework.pin(motion=True)
    arm, reader = NeroFeedback("can0", motion=True), NeroFeedback("can0")
    assert arm.device is reader.device
    target = [0.1, -1.7449, 0.2, 0.3, 0.1, -0.2, 0.2]  # joint2 near -100°, where the taught path goes
    arm.move(target)
    assert np.allclose(reader.read_joints()["joints_rad"], target)
    assert np.allclose(reader.read(), np.asarray(arm.device.kinematics.forward(target, False)).reshape(4, 4))
    arm.hold()
    assert arm.move_hand([0.0] * 6, 1.0)["status"] == "unverified"
    arm.close(), reader.close()
    assert framework._device is not None  # The Web job keeps its lease until it ends.
    framework.close()
    framework.pin(motion=False)
    with pytest.raises(RuntimeError, match="只读"):
        NeroFeedback("can0", motion=True)


def fake_nero(site, tmp_path, mode):
    """device.yaml for the real Nero driver on the CAN-free SDK fixture; returns (channel, sdk)."""
    worker = SOURCE / "drivers/common/agx_session/agx_worker.py"
    sdk = tmp_path / "sdk"
    shutil.copytree(SOURCE / "tests/fake_sdk", sdk)
    commit = re.search(r'SDK_COMMIT = "([0-9a-f]+)"', worker.read_text()).group(1)
    (sdk / "UPSTREAM_COMMIT").write_text(commit + "\n")
    channel = f"t{os.getpid() % 0x10000:04x}_{mode}"
    device = {
        "driver": "agx_nero_revo2",
        "model": "nero",
        "arm": {"device_id": "arm_main", "resource_id": f"agx_{channel}", "joints": JOINTS, "timeout_s": 20},
        "options": {
            "channel": channel,
            "worker": str(worker),
            "sdk_root": str(sdk),
            "python": os.path.realpath(sys.executable),
        },
    }
    (site / "device.yaml").write_text(json.dumps({"schema_version": 3, "device": device, "steps": []}))
    return channel, sdk


def test_taught_route_is_one_continuous_stream(site, tmp_path):
    from auto_collect import stream_smooth_route
    from sensors import NeroFeedback

    channel, sdk = fake_nero(site, tmp_path, "path")
    arm = NeroFeedback(channel, motion=True)
    try:
        arm.speed_percent = 40
        route = [
            arm.read_joints()["joints_rad"],
            [0.1, -0.1, 0.1, 0.2, 0.0, 0.0, 0.0],
            [0.2, -0.2, 0.1, 0.3, 0.1, 0.0, 0.1],
        ]
        stream_smooth_route(arm, route, 20.0, 20.0)
        assert np.allclose(arm.read_joints()["joints_rad"], route[-1])
    finally:
        arm.close()
    events = [json.loads(line) for line in (sdk / "pyAgxArm/recovery-events.jsonl").read_text().splitlines()]
    operations = [event["op"] for event in events]
    # One js stream, no stop at the middle point and no switch to the point (j) mode to settle.
    assert operations.count("move_js") > 20 and "move_j" not in operations
    assert [event["mode"] for event in events if event["op"] == "set_motion_mode"] == ["js"]
    assert {"op": "set_speed_percent", "percent": 40} in events


def test_ctrl_c_cancels_a_stalled_move_and_the_arm_holds(site, tmp_path):
    from sensors import NeroFeedback

    channel, sdk = fake_nero(site, tmp_path, "stall")  # The fixture never reaches a new target.
    arm = NeroFeedback(channel, motion=True)
    try:
        arm.speed_percent = 40  # The original configuration value; framework moves are capped.
        threading.Timer(1.0, os.kill, (os.getpid(), signal.SIGINT)).start()
        started = time.monotonic()
        with pytest.raises(KeyboardInterrupt):
            arm.move([0.2] * 7)
        assert time.monotonic() - started < 6
        assert arm.read_joints()["joints_rad"] == [0.0] * 7
    finally:
        arm.close()
    events = [json.loads(line) for line in (sdk / "pyAgxArm/recovery-events.jsonl").read_text().splitlines()]
    moves = [event for event in events if event["op"] == "move_j"]
    assert moves[0]["target"] == [0.2] * 7 and moves[-1]["target"] == [0.0] * 7  # Commanded, then held.
    assert {"op": "set_speed_percent", "percent": 10} in events
    assert signal.getsignal(signal.SIGINT) is signal.default_int_handler
