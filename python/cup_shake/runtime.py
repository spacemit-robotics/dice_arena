# Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
# SPDX-License-Identifier: Apache-2.0
"""Serialized orchestration over C++ device control and C++ cup business policy."""

from concurrent.futures import ThreadPoolExecutor
import contextlib
import json
import math
import os
from pathlib import Path
import threading
import time
import uuid
from spacemit_manipulation import DeviceClient
from .planners import make_planner, file_hash
from .policy import CupPolicy


# The task states that leave nothing to inspect: no cup possibly held, no fault.
IDLE_STATES = ("needs_home", "ready")
# Hand poses of a fixture planner; a green cup planner takes them from its own configuration.
HAND_FIELDS = ("open_positions", "grip_positions", "duration_s", "gestures")


def check_hand(hand):
    """Hand positions are 0 closed, 1 open per channel; the duration is the Revo2 range."""
    for name in ("open", "grip"):
        values = hand[name]
        if (
            not isinstance(values, list)
            or not values
            or any(
                type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1
                for v in values
            )
        ):
            raise ValueError("invalid normalized hand pose")
    duration = hand["duration_s"]
    if (
        type(duration) not in (float, int)
        or not math.isfinite(duration)
        or not 0 < duration <= 2.55
    ):
        raise ValueError("hand duration must be in (0, 2.55] s")
    return hand


class CupApplication:
    def __init__(self, config_file, *, allow_motion=True):
        self.config_file = Path(config_file).resolve()
        self.config = json.loads(self.config_file.read_text(encoding="utf-8"))
        required = {"schema_version", "executable", "device_plan", "policy_library", "planner"}
        required |= {"speed_scale"}
        allowed = required | {
            "grip_ack_directory",
            "home_tolerance_rad",
            "grip_confirmation",
            "state_file",
            *HAND_FIELDS,
        }
        if set(self.config) - allowed or required - set(self.config):
            raise ValueError("invalid cup application configuration")
        if self.config["schema_version"] != 3:  # Version 3: hand poses come from the planner.
            raise ValueError(
                "cup application configuration needs schema_version 3; "
                "move it aside and generate a new one with `dice-arena configure`"
            )
        fixture = self.config["planner"].get("type") == "fixture"
        hand_fields = {name for name in HAND_FIELDS if name in self.config}
        if fixture and hand_fields != set(HAND_FIELDS):
            raise ValueError("a fixture planner needs " + ", ".join(HAND_FIELDS))
        if not fixture and hand_fields:
            raise ValueError(
                "hand poses come from the planner configuration (green_cup.json); remove "
                + ", ".join(sorted(hand_fields))
            )
        self.hand = (
            check_hand(
                dict(
                    open=self.config["open_positions"],
                    grip=self.config["grip_positions"],
                    duration_s=self.config["duration_s"],
                )
            )
            if fixture
            else None
        )
        self._lock = threading.Lock()
        self.client = self.planner = self.policy = None
        value = self.config["speed_scale"]
        if type(value) not in (float, int) or not math.isfinite(value) or not 0 < value <= 0.1:
            raise ValueError("speed_scale must be in (0, 0.1]")
        if self.config.get("grip_confirmation", "none") not in ("none", "operator"):
            raise ValueError("grip_confirmation must be none or operator")
        self.allow_motion = allow_motion
        self._hand_open = (
            None  # Last commanded hand pose is open: True/False, None before any command.
        )
        self._moved = False  # The current command has sent a motion to the device.
        self.hashes = {
            str(self.config_file): file_hash(self.config_file),
            str(self.path("device_plan")): file_hash(self.path("device_plan")),
        }

    @property
    def state_file(self):
        """Where a task state that needs the operator outlives the process; None if not kept."""
        return self.path("state_file") if "state_file" in self.config else None

    def recorded_state(self):
        """The task state a previous process left behind, or None."""
        path = self.state_file
        if path is None or not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def reset(self):
        """Forget a recorded task state after the operator has inspected the arm, hand and cup.
        Opens no device and moves nothing. Returns the record that was removed, or None."""
        record = self.recorded_state()
        if record is not None:
            self.state_file.unlink()
        return record

    def _record(self, reason=""):
        """Keep a task state that needs the operator (cup possibly held, a phase interrupted, a
        fault) across restarts; an idle task leaves no record."""
        path = self.state_file
        if path is None or self.policy is None:
            return
        if self.policy.state in IDLE_STATES and not self.policy.active:
            path.unlink(missing_ok=True)
            return
        record = dict(
            state=self.policy.state,
            phase=self.policy.active,
            reason=reason,
            time_unix_s=round(time.time(), 3),
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(temporary, path)

    def path(self, name):
        return (self.config_file.parent / self.config[name]).resolve()

    def connect(self, vision=True):
        """vision=False: no camera or model startup, for commands that only move (home)."""
        if self.client is not None:
            return
        self.policy = CupPolicy(self.path("policy_library"))
        record = self.recorded_state()
        if record is not None:  # The previous process ended while the cup may be held.
            self.policy.step("failure", 2)
        starter = ThreadPoolExecutor(max_workers=1, thread_name_prefix="cup-device")
        # The device process starts while the planner imports its algorithms (about 2 s on K3).
        device = starter.submit(
            DeviceClient,
            self.path("executable"),
            self.path("device_plan"),
            allow_motion=self.allow_motion,
        )
        starter.shutdown(wait=False)
        try:
            planner = self.config["planner"]
            # A fixture planner is allowed only on a device that reports the mock driver.
            driver = device.result().metadata["driver"] if planner["type"] == "fixture" else None
            self.planner = make_planner(
                planner, lambda: self.client.state(), driver, self.config_file.parent
            )
            if self.hand is None:
                self.hand = check_hand(self.planner.hand_poses())
            if self.allow_motion and vision and hasattr(self.planner, "warm_up"):
                # Camera, model and collision geometry load in the background.
                self.planner.warm_up()
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
            raise RuntimeError(
                "application/device configuration changed; recreate after inspection"
            )

    def _phase(self, name, operation, deadline, cancelled, on_event):
        self._check(deadline, cancelled)
        self.policy.step(name, 0)
        self._record()
        try:
            on_event(dict(event="robot", phase=name, progress=0))
            started = time.monotonic()
            operation()
            self._check(deadline, cancelled)
            self.policy.step(name, 1)
            self._record()
            timing = dict(elapsed_s=round(time.monotonic() - started, 2))
            if getattr(self, "_plan_s", None) is not None:
                timing["plan_s"], self._plan_s = self._plan_s, None
            on_event(dict(event="robot", phase=name, progress=1, **timing))
        except BaseException:
            # Nothing sent to the device yet: the task stays as it was. Otherwise it latches.
            if self._moved:
                self.policy.step(name, 2)
            else:
                self.policy.abandon(name)
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
                self._moved = True
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
                while time.monotonic() < end:  # The remaining finger time.
                    if cancelled() or time.monotonic() >= deadline:
                        raise RuntimeError(
                            "application cancelled/deadline expired; no automatic recovery"
                        )
                    time.sleep(min(0.02, max(0.0, end - time.monotonic())))
            else:
                self._moved = True
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
        self._moved = True
        self.client.move_effector(
            positions,
            self.hand["duration_s"],
            timeout=min(120, deadline - time.monotonic()),
            is_cancelled=cancelled,
            allow_unverified=self._open_loop_hand(),
        )
        self._hand_open = list(positions) == list(self.hand["open"])

    def at_home(self):
        state = self.client.state()
        tolerance = self.config.get("home_tolerance_rad", math.radians(0.5))
        if not math.isfinite(tolerance) or not 0 < tolerance <= 0.01:
            raise ValueError("invalid home tolerance")
        arm_home = (
            not state["fault"]
            and not state["moving"]
            and len(state["joints_rad"]) == len(self.planner.home)
            and all(abs(a - b) <= tolerance for a, b in zip(state["joints_rad"], self.planner.home))
        )
        if self._open_loop_hand(state):
            # Hand position cannot be measured: it counts as open only once it was commanded open
            # by this process; after a start the hand is opened before any grasp.
            return arm_home and not state.get("effector_fault", True) and self._hand_open is True
        return (
            arm_home
            and len(state.get("effector_positions", [])) == len(self.hand["open"])
            and all(
                abs(a - b) <= 0.02 for a, b in zip(state["effector_positions"], self.hand["open"])
            )
            and not state.get("effector_fault", True)
        )

    def _verify_grip(self, deadline, cancelled, on_event):
        """Evidence that allows the lift: the delivered grip command (grip_confirmation "none"), or
        a fresh operator acknowledgement file per grasp ("operator")."""
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
        on_event(
            dict(
                event="robot",
                phase="await_grip_confirmation",
                token=token,
                acknowledgement=str(path),
            )
        )
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

    def command(
        self,
        command,
        *,
        on_event=lambda _event: None,
        is_cancelled=lambda: False,
        timeout_seconds=120,
    ):
        deadline = time.monotonic() + timeout_seconds
        if not 0 < timeout_seconds <= 180:
            return dict(status="failed", reason="timeout must be (0,180] seconds")
        if not self._lock.acquire(timeout=timeout_seconds):
            return dict(status="failed", reason="application queue deadline expired")
        self._moved = False
        try:
            self.connect()
            if self.policy.state == "fault" and self.recorded_state() is not None:
                record = self.recorded_state()
                detail = f"; {record['reason']}" if record.get("reason") else ""
                raise RuntimeError(
                    f"task state {record['state']} needs the operator{detail}. Inspect the arm, "
                    "hand and cup, then run `dice-arena reset` and start the program again"
                )
            self._check(deadline, is_cancelled)
            if command == "query_pose" or (
                command == "ensure_home" and self._hand_open and self.at_home()
            ):
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
                # The arm to HOME with the hand opening. The task policy allows it only from the
                # idle task (never while possibly holding the cup, never after a fault).
                if hasattr(self.planner, "gesture"):
                    self._deliver(
                        [self.planner.gesture("home", self.client.state())], deadline, is_cancelled
                    )
                else:
                    self._deliver(
                        [
                            dict(
                                kind="point",
                                target=self.planner.home,
                                speed_scale=self.config["speed_scale"],
                            )
                        ],
                        deadline,
                        is_cancelled,
                    )
                    self._hand(self.hand["open"], deadline, is_cancelled)

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
                if not self.at_home():  # Home first, opening the hand.
                    phase("home", home)
                elif self.policy.state == "needs_home":
                    phase("home", lambda: None)
                self._check(deadline, is_cancelled)
                started = time.monotonic()
                if hasattr(self.planner, "ready"):  # Camera/model startup; only the first waits.
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
                phase(
                    "grip",
                    lambda: self._hand(self.hand["grip"], deadline, is_cancelled),
                )
                evidence = self._verify_grip(deadline, is_cancelled, on_event)
                self.policy.confirm_grip()
                self._record()
                phase("lift", lambda: move("lift"))
                return dict(
                    status="completed", grip_evidence=evidence, physical_grip_verified=False
                )
            if command == "shake_dice":
                phase("shake", lambda: move("shake"))
            elif command == "settle_dice":
                phase("lower", lambda: move("lower"))
                phase(
                    "open",
                    lambda: self._hand(self.hand["open"], deadline, is_cancelled),
                )
                phase("return_home", lambda: move("return_home"))
            elif command.startswith("gesture:") and hasattr(self.planner, "gesture"):
                # Result feedback: the arm to the gesture pose with the hand together; it holds
                # there until a home command.
                name = command.split(":", 1)[1]
                phase(
                    "gesture",
                    lambda: self._deliver(
                        [self.planner.gesture(name, self.client.state())], deadline, is_cancelled
                    ),
                )
            elif command.startswith("gesture:"):
                gesture = self.config.get("gestures", {}).get(command.split(":", 1)[1])
                if gesture is None:
                    raise ValueError("gesture not registered")

                def feedback_gesture():
                    self._hand(gesture, deadline, is_cancelled)
                    self._hand(self.hand["open"], deadline, is_cancelled)

                phase("gesture", feedback_gesture)
            else:
                raise ValueError("unknown application command")
            return dict(status="completed", physical_grip_verified=False)
        except Exception as error:
            # A failure after a motion was sent latches the task; before any motion (no cup seen,
            # a refused command, a cancelled start) the task stays as it was and may be retried.
            if self.policy is not None and command != "query_pose" and self._moved:
                self.policy.step("failure", 2)
            if self.policy is not None:
                self._record(str(error))
            return dict(
                status="failed",
                reason=str(error),
                state=self.policy.state if self.policy else "disconnected",
            )
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
