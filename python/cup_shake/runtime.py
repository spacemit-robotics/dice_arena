# Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
# SPDX-License-Identifier: Apache-2.0
"""Serialized orchestration over C++ device control and C++ cup business policy."""

from concurrent.futures import ThreadPoolExecutor
import contextlib
import json
import math
from pathlib import Path
import threading
import time
import uuid
from spacemit_manipulation import DeviceClient
from .planners import make_planner, file_hash
from .policy import CupPolicy


class CupApplication:
    def __init__(self, config_file, *, allow_motion=True):
        self.config_file = Path(config_file).resolve()
        self.config = json.loads(self.config_file.read_text(encoding="utf-8"))
        required = {
            "schema_version",
            "executable",
            "device_plan",
            "policy_library",
            "planner",
            "speed_scale",
            "open_positions",
            "grip_positions",
            "duration_s",
        }
        allowed = required | {"grip_ack_directory", "gestures", "home_tolerance_rad", "grip_confirmation"}
        if set(self.config) - allowed or required - set(self.config) or self.config["schema_version"] != 1:
            raise ValueError("invalid cup application configuration")
        self._lock = threading.Lock()
        self.client = self.planner = self.policy = None
        for name in ("speed_scale", "duration_s"):
            value = self.config[name]
            if type(value) not in (float, int) or not math.isfinite(value) or value <= 0:
                raise ValueError("invalid " + name)
        if self.config["speed_scale"] > 0.1 or self.config["duration_s"] > 2.55:
            raise ValueError("application speed <=0.1 and hand duration <=2.55 required")
        for name in ("open_positions", "grip_positions"):
            values = self.config[name]
            if (
                not isinstance(values, list)
                or not values
                or any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in values)
            ):
                raise ValueError("invalid normalized hand pose")
        if self.config.get("grip_confirmation", "none") not in ("none", "operator"):
            raise ValueError("grip_confirmation must be none or operator")
        self.allow_motion = allow_motion
        self._hand_open = None  # Last commanded hand pose is open: True/False, None before any command.
        self.hashes = {
            str(self.config_file): file_hash(self.config_file),
            str(self.path("device_plan")): file_hash(self.path("device_plan")),
        }

    def path(self, name):
        return (self.config_file.parent / self.config[name]).resolve()

    def connect(self, vision=True):
        """vision=False: no camera or model startup, for commands that only move (home)."""
        if self.client is not None:
            return
        self.policy = CupPolicy(self.path("policy_library"))
        starter = ThreadPoolExecutor(max_workers=1, thread_name_prefix="cup-device")
        # The device process starts while the planner imports its algorithms (about 2 s on K3).
        device = starter.submit(
            DeviceClient, self.path("executable"), self.path("device_plan"), allow_motion=self.allow_motion
        )
        starter.shutdown(wait=False)
        try:
            planner = self.config["planner"]
            # A fixture planner is allowed only on a device that reports the mock driver.
            driver = device.result().metadata["driver"] if planner["type"] == "fixture" else None
            self.planner = make_planner(planner, lambda: self.client.state(), driver, self.config_file.parent)
            if self.allow_motion and vision and hasattr(self.planner, "warm_up"):
                self.planner.warm_up()  # Camera, model and collision geometry load in the background.
            self.client = device.result()
        except BaseException:
            with contextlib.suppress(Exception):
                self.client = device.result()  # Started anyway: closed below, never left running.
            self.close()
            raise

    def _check(self, deadline, cancelled):
        if cancelled() or time.monotonic() >= deadline:
            raise RuntimeError("application cancelled/deadline expired; no automatic recovery")
        if any(file_hash(path) != digest for path, digest in self.hashes.items()):
            raise RuntimeError("application/device configuration changed; recreate after inspection")

    def _phase(self, name, operation, deadline, cancelled, on_event):
        self._check(deadline, cancelled)
        self.policy.step(name, 0)
        try:
            on_event(dict(event="robot", phase=name, progress=0))
            started = time.monotonic()
            operation()
            self._check(deadline, cancelled)
            self.policy.step(name, 1)
            timing = dict(elapsed_s=round(time.monotonic() - started, 2))
            if getattr(self, "_plan_s", None) is not None:
                timing["plan_s"], self._plan_s = self._plan_s, None
            on_event(dict(event="robot", phase=name, progress=1, **timing))
        except BaseException:
            self.policy.step(name, 2)
            raise

    def _move(self, phase, deadline, cancelled, on_event=lambda _event: None):
        state, started = self.client.state(), time.monotonic()
        if hasattr(self.planner, "motions"):  # The planner chooses how each phase is delivered.
            motions = self.planner.motions(phase, state)
        else:
            motions = [
                dict(kind="point", target=target, speed_scale=self.config["speed_scale"])
                for target in self.planner.targets(phase, state)
            ]
        self._plan_s = round(time.monotonic() - started, 2)
        self._deliver(motions, deadline, cancelled)
        if phase == "lower":
            note = self.planner.verify_lower(self.client.state())
            if note:
                on_event(dict(event="robot", phase=phase, warning=note))

    def _deliver(self, motions, deadline, cancelled):
        for motion in motions:
            self._check(deadline, cancelled)
            timeout = min(120, deadline - time.monotonic())
            if motion["kind"] == "trajectory":
                schedule = motion.get("effector_schedule", ())
                if schedule:
                    self._hand_open = None  # Unknown until the gesture has completed.
                self.client.move_arm_trajectory(
                    motion["times_s"],
                    motion["positions_rad"],
                    command_rate_hz=motion["command_rate_hz"],
                    max_step_rad=motion["max_step_rad"],
                    speed_scale=motion["speed_scale"],
                    tolerance_rad=motion["tolerance_rad"],
                    wait_for_arrival=motion.get("wait_for_arrival", True),
                    effector_schedule=schedule,
                    allow_unverified=bool(schedule),
                    timeout=timeout,
                    is_cancelled=cancelled,
                )
                if schedule:
                    self._hand_open = motion.get("hand_open", False)
                end = time.monotonic() + motion.get("hold_s", 0)
                while time.monotonic() < end:  # The remaining finger time, as the original waited it.
                    if cancelled() or time.monotonic() >= deadline:
                        raise RuntimeError("application cancelled/deadline expired; no automatic recovery")
                    time.sleep(min(0.02, max(0.0, end - time.monotonic())))
            else:
                self.client.move_arm(
                    motion["target"],
                    motion["speed_scale"],
                    tolerance_rad=motion.get("tolerance_rad", 0.0),
                    wait_for_arrival=motion.get("wait_for_arrival", True),
                    resend_interval_s=motion.get("resend_interval_s", 0.0),
                    timeout=timeout,
                    is_cancelled=cancelled,
                )

    def _open_loop_hand(self, state=None):
        """The device reports no hand position: moves are delivered unverified, never as reached."""
        return (state or self.client.state()).get("effector_feedback") == "none"

    def _hand(self, positions, deadline, cancelled):
        self._check(deadline, cancelled)
        self._hand_open = None
        self.client.move_effector(
            positions,
            self.config["duration_s"],
            timeout=min(120, deadline - time.monotonic()),
            is_cancelled=cancelled,
            allow_unverified=self._open_loop_hand(),
        )
        self._hand_open = list(positions) == list(self.config["open_positions"])

    def at_home(self):
        state = self.client.state()
        tolerance = self.config.get("home_tolerance_rad", math.radians(0.5))  # The original "already home".
        if not math.isfinite(tolerance) or not 0 < tolerance <= 0.01:
            raise ValueError("invalid home tolerance")
        arm_home = (
            not state["fault"]
            and not state["moving"]
            and len(state["joints_rad"]) == len(self.planner.home)
            and all(abs(a - b) <= tolerance for a, b in zip(state["joints_rad"], self.planner.home))
        )
        if self._open_loop_hand(state):
            # Hand position cannot be measured: the last commanded pose must not be a closed one (before
            # any command the operator has opened it).
            return arm_home and not state.get("effector_fault", True) and self._hand_open is not False
        return (
            arm_home
            and len(state.get("effector_positions", [])) == len(self.config["open_positions"])
            and all(abs(a - b) <= 0.02 for a, b in zip(state["effector_positions"], self.config["open_positions"]))
            and not state.get("effector_fault", True)
        )

    def _verify_grip(self, deadline, cancelled, on_event):
        """Evidence that allows the lift. As the original application, the delivered grip command is enough
        (grip_confirmation "none"); "operator" waits for a fresh acknowledgement file per grasp."""
        if self.client.metadata["driver"] == "mock_device":
            return "mock_only"
        mode = self.config.get("grip_confirmation", "none")
        if mode == "none":
            return "grip_commanded"
        if mode != "operator":
            raise ValueError("grip_confirmation must be none or operator")
        if "grip_ack_directory" not in self.config:
            raise RuntimeError("physical grip verifier not configured; lift forbidden")
        token = uuid.uuid4().hex
        path = self.path("grip_ack_directory") / (token + ".json")
        started = time.time()
        on_event(dict(event="robot", phase="await_grip_confirmation", token=token, acknowledgement=str(path)))
        while True:
            self._check(deadline, cancelled)
            if path.exists():
                if path.stat().st_size > 4096:
                    raise ValueError("oversized grip acknowledgement")
                report = json.loads(path.read_text(encoding="utf-8"))
                if (
                    report.get("token") != token
                    or not report.get("operator")
                    or not started <= report.get("checked_epoch_s", 0) <= time.time()
                ):
                    raise ValueError("invalid/stale operator grip acknowledgement")
                return "operator_declared:" + str(report["operator"])
            time.sleep(0.05)

    def command(self, command, *, on_event=lambda _event: None, is_cancelled=lambda: False, timeout_seconds=120):
        deadline = time.monotonic() + timeout_seconds
        if not 0 < timeout_seconds <= 180:
            return dict(status="failed", reason="timeout must be (0,180] seconds")
        if not self._lock.acquire(timeout=timeout_seconds):
            return dict(status="failed", reason="application queue deadline expired")
        try:
            self.connect()
            self._check(deadline, is_cancelled)
            if command == "query_pose" or (command == "ensure_home" and self._hand_open and self.at_home()):
                home = self.at_home()
                return dict(
                    status="completed" if home and self.policy.state != "fault" else "failed",
                    at_home=home,
                    task_state=self.policy.state,
                )
            if not self.allow_motion:
                raise RuntimeError("application motion permission absent")

            def phase(name, operation):
                self._phase(name, operation, deadline, is_cancelled, on_event)

            def home():
                # The original "home" action: the arm to HOME with the hand opening. The task policy allows
                # it only from the idle task (never while possibly holding the cup, never after a fault).
                if hasattr(self.planner, "gesture"):
                    self._deliver([self.planner.gesture("home", self.client.state())], deadline, is_cancelled)
                else:
                    self._deliver(
                        [dict(kind="point", target=self.planner.home, speed_scale=self.config["speed_scale"])],
                        deadline,
                        is_cancelled,
                    )
                    self._hand(self.config["open_positions"], deadline, is_cancelled)

            if command in ("ensure_home", "reset_home"):
                phase("home", home)
                return dict(
                    status="completed",
                    at_home=self.at_home(),
                    task_state=self.policy.state,
                    physical_grip_verified=False,
                )

            def move(name):
                self._move(name, deadline, is_cancelled, on_event)

            if command == "grasp_cup":
                if self.policy.state not in ("needs_home", "ready"):
                    raise RuntimeError("grasp requires the idle task state: no cup held, no fault")
                if not self.at_home():  # The original HOME phase: home first, opening the hand.
                    phase("home", home)
                elif self.policy.state == "needs_home":
                    phase("home", lambda: None)
                self._check(deadline, is_cancelled)
                started = time.monotonic()
                if hasattr(self.planner, "ready"):  # Camera/model startup; only the first command waits.
                    self.planner.ready()
                startup, started = time.monotonic() - started, time.monotonic()
                self.planner.prepare()  # Capture, detection and grasp planning; no motion.
                on_event(
                    dict(
                        event="robot",
                        phase="prepare",
                        elapsed_s=round(time.monotonic() - started, 2),
                        startup_wait_s=round(startup, 2),
                    )
                )
                phase("approach", lambda: move("approach"))
                phase("grip", lambda: self._hand(self.config["grip_positions"], deadline, is_cancelled))
                evidence = self._verify_grip(deadline, is_cancelled, on_event)
                self.policy.confirm_grip()
                phase("lift", lambda: move("lift"))
                return dict(status="completed", grip_evidence=evidence, physical_grip_verified=False)
            if command == "shake_dice":
                phase("shake", lambda: move("shake"))
            elif command == "settle_dice":
                phase("lower", lambda: move("lower"))
                phase("open", lambda: self._hand(self.config["open_positions"], deadline, is_cancelled))
                phase("return_home", lambda: move("return_home"))
            elif command.startswith("gesture:") and hasattr(self.planner, "gesture"):
                # The original result feedback: the arm to the gesture pose with the hand together; it holds
                # there until a home command.
                name = command.split(":", 1)[1]
                phase(
                    "gesture",
                    lambda: self._deliver([self.planner.gesture(name, self.client.state())], deadline, is_cancelled),
                )
            elif command.startswith("gesture:"):
                gesture = self.config.get("gestures", {}).get(command.split(":", 1)[1])
                if gesture is None:
                    raise ValueError("gesture not registered")

                def feedback_gesture():
                    self._hand(gesture, deadline, is_cancelled)
                    self._hand(self.config["open_positions"], deadline, is_cancelled)

                phase("gesture", feedback_gesture)
            else:
                raise ValueError("unknown application command")
            return dict(status="completed", physical_grip_verified=False)
        except Exception as error:
            if self.policy is not None and command != "query_pose":
                self.policy.step("failure", 2)
            return dict(status="failed", reason=str(error), state=self.policy.state if self.policy else "disconnected")
        finally:
            self._lock.release()

    def close(self):
        # Closing never releases fingers, homes, disables or replays a task.
        try:
            if self.planner is not None:
                self.planner.close()
        finally:
            try:
                if self.client is not None:
                    self.client.close()
            finally:
                if self.policy is not None:
                    self.policy.close()
                self.client = self.planner = self.policy = None
