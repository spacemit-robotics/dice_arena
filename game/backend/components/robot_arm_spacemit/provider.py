# Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
# SPDX-License-Identifier: Apache-2.0
"""Dice Arena RobotProvider on the cup application. No vendor imports or auto-restart; homes as the
original provider."""

import os
from pathlib import Path
import threading
import time
from core.robot import RobotProvider
from cup_shake import CupApplication
from spacemit_manipulation.operator_support import default_site


class SpacemitRobotProvider(RobotProvider):
    id = "robot_arm_spacemit"
    name = "SpacemiT manipulation"
    version = "0.1.0"
    home_on_boot = False

    def __init__(self, manifest=None):
        super().__init__(manifest)
        # The site's cup application (`cup-shake configure`); `dice-arena serve` passes it explicitly.
        application = Path(os.environ.get("SPACEMIT_CUP_APPLICATION") or Path(default_site()) / "cup_application.json")
        self.app = CupApplication(application.resolve())
        self._lock = threading.Lock()
        self._closed = False

    def health(self):
        return dict(
            id=self.id,
            type=self.type,
            ok=not self._closed,
            home_on_boot=False,
            connection="prewarmed on game entry; no startup motion",
        )

    def ensure_started(self):
        """Connect in the background on game entry, so the rules speech covers the device, camera,
        model and geometry startup (the original resident prewarm). Never blocks the caller; never
        enables, homes or moves. A failure is logged and the first command connects again."""
        if self._lock.acquire(blocking=False):  # A command in flight has connected already.

            def start():
                try:
                    if not self._closed:
                        self.app.connect()
                except Exception as error:  # noqa: BLE001 - best effort, as the original prewarm
                    print(f"[robot_arm_spacemit] prewarm failed: {error}", flush=True)
                finally:
                    self._lock.release()

            threading.Thread(target=start, name="spacemit-prewarm", daemon=True).start()
        return self.health()

    def _command(self, name, on_event, is_cancelled, timeout_seconds):
        timeout = 120 if timeout_seconds is None else timeout_seconds
        if not isinstance(timeout, (int, float)) or not 0 < timeout <= 180:
            return dict(status="failed", reason="invalid timeout")
        deadline = time.monotonic() + timeout
        if not self._lock.acquire(timeout=timeout):
            return dict(status="failed", reason="provider queue deadline expired")
        try:
            if self._closed:
                return dict(status="failed", reason="provider closed; no automatic restart")
            return self.app.command(
                name, on_event=on_event, is_cancelled=is_cancelled, timeout_seconds=max(0, deadline - time.monotonic())
            )
        except Exception as error:
            return dict(status="failed", reason=str(error))
        finally:
            self._lock.release()

    def grasp_cup(self, *, on_event, is_cancelled, timeout_seconds=None):
        return self._command("grasp_cup", on_event, is_cancelled, timeout_seconds)

    def shake_dice(self, *, on_event, is_cancelled, timeout_seconds=None):
        return self._command("shake_dice", on_event, is_cancelled, timeout_seconds)

    def settle_dice(self, *, on_event, is_cancelled, timeout_seconds=None):
        return self._command("settle_dice", on_event, is_cancelled, timeout_seconds)

    def feedback(self, kind, *, on_event, is_cancelled, timeout_seconds=None):
        # win/lose/draw: the original arm-and-hand gesture; the arm holds it until the post-round home.
        return self._command("gesture:" + kind, on_event, is_cancelled, timeout_seconds)

    def prepare_throw(self, *, on_event, is_cancelled, timeout_seconds=None):
        return dict(status="failed", reason="RPS choreography is not part of the cup application")

    def throw_gesture(self, gesture=None, *, prepared=False, on_event, is_cancelled, timeout_seconds=None):
        del gesture, prepared
        return dict(status="failed", reason="RPS choreography is not part of the cup application")

    def query_pose(self, *, on_event, is_cancelled, timeout_seconds=None):
        return self._command("query_pose", on_event, is_cancelled, timeout_seconds)

    def reset_home(self, *, on_event, is_cancelled, timeout_seconds=None):
        # The original home action: the arm to HOME with the hand opening. Refused while the cup may be
        # held or after a fault: those need the operator, never an automatic recovery.
        return self._command("reset_home", on_event, is_cancelled, timeout_seconds)

    def ensure_home(self, *, on_event, is_cancelled, timeout_seconds=None):
        # The post-round home: no motion when already at HOME with the hand open, else the home action.
        return self._command("ensure_home", on_event, is_cancelled, timeout_seconds)

    def shutdown(self):
        with self._lock:
            self._closed = True
            self.app.close()
