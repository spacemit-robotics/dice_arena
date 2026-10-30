"""Arm and hand access through the SpacemiT manipulation framework.

The only module of this program that reaches hardware. Routes are continuous joint paths and
single targets are verified point moves, both executed by `manipulation-device`, which holds the
host-wide device lease, checks joint limits and holds the arm when a motion is cancelled.
pyAgxArm is blocked in this process, so no code path can open CAN beside the framework.

Environment (set by calibrate.sh / calibrate_web.sh):
  MANIPULATION_PREFIX  installed framework (required)
  MANIPULATION_SITE    site directory with device.yaml (default ~/.local/share/spacemit-manipulation/site)
  MANIPULATION_DEVICE  explicit device configuration instead of SITE/device.yaml
"""

import importlib.abc
import json
import math
import os
import signal
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import numpy as np

# Single point moves run at the controller's own speed, so they are limited to this percentage.
# Routes are bounded by their speed/acceleration profile and use the configured percentage.
MAX_SPEED_PERCENT = 10
# Routes run in the controller's streaming (js) mode, which stops a few tenths of a degree short;
# arrival at a route's end is judged within this tolerance, as the original program did.
ROUTE_TOLERANCE_DEG = 0.8
HOLD_SPEED_PERCENT = 5
MOVE_TIMEOUT_S = 120


class _NoVendorSdk(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.partition(".")[0] == "pyAgxArm":
            raise ImportError("标定程序只经 manipulation 框架访问机械臂和灵巧手，禁止直接导入 pyAgxArm")
        return None


if not any(type(finder).__name__ == "_NoVendorSdk" for finder in sys.meta_path):
    sys.meta_path.insert(0, _NoVendorSdk())
# Modules import this as `framework` or `calibration.framework`: keep one session per process.
for _name in ("framework", "calibration.framework"):
    sys.modules.setdefault(_name, sys.modules[__name__])


def _context():
    prefix = os.environ.get("MANIPULATION_PREFIX")
    if not prefix:
        raise RuntimeError("未设置 MANIPULATION_PREFIX；请用 calibrate.sh 或 calibrate_web.sh 启动")
    layout = json.loads((Path(prefix) / ".spacemit-manipulation.json").read_text())
    modules = str(Path(prefix) / layout["pythondir"])
    if modules not in sys.path:
        sys.path.append(modules)
    from spacemit_manipulation.operator_support import Context, default_site

    return Context(SimpleNamespace(prefix=prefix, site=os.environ.get("MANIPULATION_SITE") or default_site()))


def robot_model(context=None):
    """The site robot's kinematic description (device.model in device.yaml); opens no device."""
    context = context or _context()
    from spacemit_manipulation.urdf_fk import UrdfKinematics

    model_file = context.model(context.plan(os.environ.get("MANIPULATION_DEVICE")))
    model = json.loads(model_file.read_text())
    return UrdfKinematics(model_file.parent / model["urdf"], model["base"], model["tip"], model["joints"])


class Device:
    """One `manipulation-device serve` session: the device lease is held until close()."""

    def __init__(self, motion):
        context = _context()  # Also makes the framework's Python modules importable.
        from spacemit_manipulation.client import DeviceClient

        plan = context.plan(os.environ.get("MANIPULATION_DEVICE"))
        self.kinematics = robot_model(context)
        self.motion, self.users, self.pinned = motion, 0, False
        try:
            self.client = DeviceClient(context.binary("manipulation-device"), plan, allow_motion=motion)
        except RuntimeError as exc:
            raise RuntimeError(f"无法打开机械臂（{plan}）：{exc}") from exc

    def state(self):
        return self.client.state()

    def flange(self, joints_rad):
        # Measured joints may sit just past the URDF limits (the controller allows them).
        return np.asarray(self.kinematics.forward(joints_rad, check_limits=False), dtype=float).reshape(4, 4)

    def move(self, target_rad, speed_percent):
        """Verified point move. Ctrl+C/SIGTERM cancel it (the device holds), then reach the caller."""
        scale = min(int(speed_percent), MAX_SPEED_PERCENT) / 100
        self._command(
            lambda cancelled: self.client.move_arm(
                list(target_rad), scale, timeout=MOVE_TIMEOUT_S, is_cancelled=cancelled
            ),
            "机械臂运动",
        )

    def move_path(self, waypoints, speed_percent, speed_deg_s, acc_deg_s2):
        """One continuous motion through the waypoints, stopping only at the last (50 Hz stream)."""
        scale = min(max(int(speed_percent), 1), 100) / 100
        self._command(
            lambda cancelled: self.client.move_arm_path(
                [list(q) for q in waypoints],
                scale,
                math.radians(speed_deg_s),
                math.radians(acc_deg_s2),
                tolerance_rad=math.radians(ROUTE_TOLERANCE_DEG),
                timeout=MOVE_TIMEOUT_S,
                is_cancelled=cancelled,
            ),
            "机械臂运动",
        )

    def move_hand(self, positions, duration_s):
        """Hand command; without hand feedback the result is `unverified` (sent, not measured)."""
        return self._command(
            lambda cancelled: self.client.move_effector(
                list(positions), duration_s, allow_unverified=True, timeout=duration_s + 10, is_cancelled=cancelled
            ),
            "灵巧手指令",
        )

    def hold(self):
        state = self.state()
        self.move(state["joints_rad"], HOLD_SPEED_PERCENT)

    def _command(self, call, label):
        from spacemit_manipulation.client import DeviceCommandError

        if not self.motion:
            raise RuntimeError(f"{label}需要运动权限；本步骤只读取设备")
        received = []
        previous = {}
        if threading.current_thread() is threading.main_thread():
            for number in (signal.SIGINT, signal.SIGTERM):
                previous[number] = signal.signal(number, lambda signum, _frame: received.append(signum))
        try:
            return call(lambda: bool(received))
        except DeviceCommandError as exc:
            result = exc.result if isinstance(exc.result, dict) else {"status": "failed", "reason": str(exc.result)}
            error = RuntimeError(
                f"{label}未完成：{result.get('status')} {result.get('detail') or result.get('reason') or ''}".strip()
            )
            if not received:
                raise error from exc
        finally:
            for number, handler in previous.items():
                signal.signal(number, handler)
            for number in received[:1]:
                signal.raise_signal(number)  # The caller's own handler decides (worker cancel, Ctrl+C).
        raise RuntimeError(f"{label}已取消")

    def close(self):
        self.client.close()


_device = None


def acquire(motion=False):
    """The process-wide session; reopened with motion permission only when nothing uses it."""
    global _device
    if _device is not None and motion and not _device.motion:
        if _device.users or _device.pinned:
            raise RuntimeError("设备已按只读方式打开，本步骤不能驱动机械臂")
        close()
    if _device is None:
        _device = Device(motion)
    _device.users += 1
    return _device


def release(device):
    device.users -= 1
    if device is _device and not device.users and not device.pinned:
        close()


def pin(motion):
    """Keep one session (and the device lease) for a whole Web job."""
    acquire(motion).pinned = True
    release(_device)


def close():
    global _device
    device, _device = _device, None
    if device is not None:
        device.close()
