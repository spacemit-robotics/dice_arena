"""Web HOME hand reset through the framework session, without waiting for hand feedback."""

import math
import time

from calibration.web.common import event

DURATION_S = 1.0


def reset_hand(arm, job):
    event(job / "hand_home.json", confirmed=False, status="running", target_0_100=[0] * 6)
    command_sent = False
    try:
        baseline = arm.read_joints()["joints_rad"]

        def monitor():
            state = arm.state()
            if state["fault"] or state["moving"] or not state["enabled"] or not state.get("position_mode", True):
                raise RuntimeError("灵巧手归零时机械臂控制状态异常")
            q = arm.read_joints()["joints_rad"]
            if max(abs(a - b) for a, b in zip(q, baseline)) > math.radians(0.2):
                raise RuntimeError("灵巧手归零时机械臂发生移动")

        monitor()
        commanded_at = time.time()
        command_sent = True  # From here the command may have reached the hand.
        result = arm.move_hand([0.0] * 6, DURATION_S)  # Returns after the commanded duration.
        monitor()
        measured = result.get("status") == "succeeded"
        proof = dict(
            confirmed=measured,
            status="completed",
            command_sent=True,
            verification="position_feedback" if measured else "command_only",
            target_0_100=[0] * 6,
            commanded_at=commanded_at,
            duration_s=DURATION_S,
            completed_at=time.time(),
        )
        event(job / "hand_home.json", **proof)
        return proof
    except BaseException as exc:
        event(
            job / "hand_home.json",
            confirmed=False,
            status="failed",
            target_0_100=[0] * 6,
            command_sent=command_sent,
            verification="command_only",
            error=str(exc) or type(exc).__name__,
        )
        raise
