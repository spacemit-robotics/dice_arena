# Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
# SPDX-License-Identifier: Apache-2.0
"""Green-cup planner over the application's algorithms (algorithms/). Never constructs Workflow/SDKClient.

Camera acquisition, inference, IK, geometry, path checks and the FAST motion profiles are the
algorithms' own; the arm and hand move only through the manipulation framework. Each phase is
delivered as the original FAST executor delivered it: synchronized trapezoid profiles at the
configured phase speeds of the controller's live joint limits, the joint-shake recipe as streamed
blended commands, and the placement as a controller-planned point move. The algorithms' own
worker, recovery loop and startup claim are not invoked; pyAgxArm cannot be imported here.
"""

from concurrent.futures import ThreadPoolExecutor
import contextlib
import hashlib
import importlib
import importlib.abc
import math
import os
from pathlib import Path
import sys
import time
import uuid
import zipfile
import numpy as np
from .planners import file_hash

KNOT_HZ = 100  # Profile knots; the device interpolates between them.
STREAM_STEP_RAD = math.radians(0.5)  # Original stream step, which sets the command rate.
COMMAND_STEP_RAD = math.radians(1)  # Original per-command step limit for transitions.
SHAKE_SETTLE_S = 2.0  # Longest wait for the arm to reach the shake centre.
ENDPOINT_RESEND_S = 0.05  # Original controller-endpoint re-send interval (LOWER).
FINGER_MAX_SPEED_S = 0.01  # Shortest Revo2 execution time: the original max-speed mode.
GEOMETRY_FORMAT = 1


def save_geometry(path, cache):
    """Store the computed collision geometry (arrays only, no pickle) for the next process."""
    arrays = dict(format=np.asarray(GEOMETRY_FORMAT))
    for key, prefix in (("table_geometry", "table"), ("geometry", "full")):
        meshes = cache[key][1]
        arrays[prefix + "_names"] = np.asarray(list(meshes))
        for i, (vertices, centers, radii) in enumerate(meshes.values()):
            arrays[f"{prefix}_{i}_vertices"] = vertices
            if centers is not None:
                arrays[f"{prefix}_{i}_centers"], arrays[f"{prefix}_{i}_radii"] = centers, radii
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with open(temporary, "wb") as stream:
        np.savez(stream, **arrays)
    os.replace(temporary, path)


def load_geometry(path, arm):
    """The stored geometry as Screen caches it, or None when absent or malformed."""

    def checked(array, columns):
        if (
            array.dtype != np.float64
            or array.ndim != (2 if columns else 1)
            or (columns and array.shape[1] != 3)
            or not np.isfinite(array).all()
        ):
            raise ValueError("malformed geometry array")
        return array

    try:
        with np.load(path, allow_pickle=False) as data:
            if int(data["format"]) != GEOMETRY_FORMAT:
                return None
            cache = {}
            for key, prefix in (("table_geometry", "table"), ("geometry", "full")):
                meshes = {}
                for i, name in enumerate(data[prefix + "_names"].tolist()):
                    vertices = checked(data[f"{prefix}_{i}_vertices"], True)
                    if prefix == "table":
                        meshes[name] = (vertices, None, None)
                    else:
                        meshes[name] = (
                            vertices,
                            checked(data[f"{prefix}_{i}_centers"], True),
                            checked(data[f"{prefix}_{i}_radii"], False),
                        )
                cache[key] = (arm, meshes)
            return cache
    except (OSError, EOFError, KeyError, ValueError, zipfile.BadZipFile):
        return None


def stamp(path):
    status = os.stat(path)
    return status.st_dev, status.st_ino, status.st_size, status.st_mtime_ns, status.st_ctime_ns


class _NoVendorSdk(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.partition(".")[0] == "pyAgxArm":
            raise ImportError("cup-shake reaches the arm only through the manipulation framework")
        return None


class LegacyGreenPlanner:
    def __init__(self, config, state):
        root = Path(config["source_root"]).resolve()
        if not any(isinstance(finder, _NoVendorSdk) for finder in sys.meta_path):
            sys.meta_path.insert(0, _NoVendorSdk())
        sys.path.insert(0, str(root))
        pipeline = importlib.import_module("cup_grasp_demo.flow.green_pipeline")
        if not Path(pipeline.__file__).resolve().is_relative_to(root):
            raise ValueError("different green-cup algorithms are already imported; use an isolated process")
        self.np, self.module, self.root, self.state = np, pipeline, root, state
        self.config = config
        self.cfg = pipeline.load_config(Path(config["config"]).resolve())
        self.cfg["allow_provisional_calibration"] = False
        # Validation is offline. The instance constructor starts the legacy startup claim: never call it.
        self.g = pipeline.validate(self.cfg)
        # The application's own gate: `calibrate.sh apply` sets it, and only a table registration
        # against the new calibration clears it; table() below checks that binding by hash.
        if self.g.get("installation_requires_calibration", False):
            raise ValueError("相机/基座重新安装：请先完成新手眼标定、桌面板登记及桌面参数更新（calibrate.sh apply）")
        self.workflow = object.__new__(pipeline.Workflow)
        work = self.workflow
        work.cfg, work.g = self.cfg, self.g
        work.root = Path(config["session_directory"]).resolve() / uuid.uuid4().hex
        work.root.mkdir(parents=True, exist_ok=False)
        work.tcp = np.asarray(pipeline.read_json(self.cfg["tcp_candidate"])["T_flange_contact_candidate"])
        work.tcp[:3, 3] += np.asarray(self.g["tcp_offset_flange_mm"]) / 1000
        work.reference = pipeline.read_json(root / self.g["reference"])
        work.kin = pipeline.Kinematics()
        work._prepared, work._vision = None, None
        work.snapshot = lambda: list(self.state()["joints_rad"])
        self.delivery = importlib.import_module("cup_grasp_demo.flow.joint_delivery")
        # Feedback gestures use the configuration as loaded (result_feedback.py), not the FAST tuning.
        self.gesture_options = self.delivery.delivery_options(dict(self.cfg.get("joint_delivery", {})))
        self.fast_settings(work)
        self.home = np.radians(pipeline.read_json(self.cfg["home"])["joints_deg"]).tolist()
        work.home = self.home
        work.table()
        # FAST settings, as the original Workflow applies them (green_pipeline.Workflow.__init__).
        work._joint_recipe = pipeline.read_json(root / self.g["joint_test_config"])
        pipeline.joint_trajectory(work._joint_recipe)
        self.profile = importlib.import_module("cup_grasp_demo.flow.joint_profile")
        self.options = self.delivery.delivery_options(self.cfg.get("joint_delivery"))
        self.settled_rad = math.radians(self.g.get("settled_joint_delta_deg", 0.5))
        sources = [
            Path(config["config"]),
            *root.glob("cup_grasp_demo/flow/*.py"),
            *root.glob("vision/**/*.py"),
            *root.glob("nero_revo2_control/*.py"),
            *root.glob("nero_revo2_control/models/**/*.urdf"),
            Path(self.cfg["calibration"]),
            Path(self.cfg["tcp_candidate"]),
            Path(self.cfg["home"]),
            root / self.g["reference"],
            root / self.g["home_table_scene"],
            root / self.g["perception"]["model"],
            root / "vision/camera.json",
            *root.glob("configs/actions/gestures/*.json"),
            *root.glob("scripts/*.py"),
        ]
        if "strategy_file" in self.g:
            strategy = self.g["strategy_file"]
            sources.append(
                root / strategy if str(strategy).endswith(".json") else root / "vision/strategy" / (strategy + ".json")
            )
        self.fingerprints = {str(path.resolve()): (stamp(path), file_hash(path)) for path in sources}
        self.place = self.held = self.lift_end = None
        self.following = self.shake_future = self.geometry_ready = None
        self.core = importlib.import_module("cup_grasp_demo.flow.core")
        self.registry = None
        self.screen_cache = {}
        self.geometry_directory = Path(config["session_directory"]).resolve().parent / "geometry"
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="green-following")

    @contextlib.contextmanager
    def geometry(self):
        """The original FAST run loads the arm/hand collision geometry once (cached_screen_geometry);
        every planner call and background task shares this planner's cache of it."""
        token = self.core._screen_cache.set(self.screen_cache)
        try:
            yield
        finally:
            self.core._screen_cache.reset(token)

    def fast_settings(self, work):
        """The FAST tuning green_pipeline.Workflow.__init__ applies unconditionally."""
        g = self.g
        if "strategy_file" in g:
            strategy = importlib.import_module("vision.strategy.loader").load_strategy(g["strategy_file"])
            for key, value in vars(strategy).items():
                g.setdefault(key, value)
        self.cfg.setdefault("joint_delivery", {})["profile"] = g.get("fast_motion_profile", "quintic")
        g["perception"]["save_debug_images"] = False
        g["perception"]["analytic_jacobian"] = g.get("fast_analytic_rim_jacobian", False)
        self.cfg["speed_percent"] = g.get("fast_speed_percent", 100)
        g["fast_completion"] = True
        g["require_arm_position"] = False
        g["finger_settle_s"] = 0.0
        g["finger_duration_s"] = g.get("fast_finger_duration_s", g["finger_duration_s"])
        g["read_hand_feedback"] = False
        if g["perception"].get("height_mode") == "fixed" and g["perception"].get("geometry_method") == "stereo_rim":
            g["perception"]["frame_count"] = 1
        if g.get("persistent_runtime", True):
            work._prepared = importlib.import_module("cup_grasp_demo.flow.green_prepared").PreparedRoutes()

    def warm_up(self):
        """Start the camera, model and collision geometry in the background (the original parallel
        startup and HOME-phase geometry preparation). VisionResources creates no arm SDK owner."""
        if self.workflow._vision is None:
            runtime = importlib.import_module("cup_grasp_demo.flow.green_runtime")
            self.workflow._vision = runtime.VisionResources(self.cfg, self.workflow.root / "capture")
        if self.geometry_ready is None:
            self.geometry_ready = self.pool.submit(self.load_geometry)

    def ensure_geometry(self):
        """The collision geometry, loaded once: in the background by warm_up, or here."""
        if self.geometry_ready is None:
            self.geometry_ready = self.pool.submit(self.load_geometry)
        self.geometry_ready.result(timeout=self.cfg["timeout_s"])

    def load_geometry(self):
        """The collision geometry the original computes once per process (about 5 s on K3), stored
        under SITE/runtime/geometry keyed by the content of every file it is computed from."""
        hand = importlib.import_module("cup_grasp_demo.hand_geometry")
        sources = [
            Path(self.core.__file__),
            Path(hand.__file__),
            Path(importlib.import_module("nero_revo2_control.kinematics").__file__),
            *sorted(path for path in Path(hand.DESCRIPTION).rglob("*") if path.is_file()),
        ]
        digest = hashlib.sha256(str(GEOMETRY_FORMAT).encode())
        for path in sources:
            digest.update(str(path.relative_to(self.root)).encode() + b"\0" + path.read_bytes())
        stored = self.geometry_directory / f"screen-{digest.hexdigest()[:32]}.npz"
        cache = load_geometry(stored, self.core.load_model()) if stored.exists() else None
        if cache is not None:
            self.screen_cache.update(cache)
            return
        with self.geometry():
            self.core.Screen(table_only=True)
            self.core.Screen()
        with contextlib.suppress(OSError):  # Without the store the next process computes it again.
            self.geometry_directory.mkdir(parents=True, exist_ok=True)
            save_geometry(stored, self.screen_cache)
            for old in self.geometry_directory.glob("screen-*.npz"):
                if old != stored:
                    old.unlink()

    def start_following(self, grasp):
        """While the arm approaches, solve the lift endpoint from the planned grasp pose (the original
        prepare_following overlap); LIFT reuses it when the hand closed there (lift_seed_close)."""
        start = list(grasp)

        def solve():
            with self.geometry():
                return start, self.workflow.vertical("lift", start, self.g["lift_mm"] / 1000, single_target=True)

        self.following = self.pool.submit(solve)

    def start_shake(self, limits):
        """Plan and table-check the shake around the lift endpoint while the cup is lifted (the
        original start_shake_prepare)."""
        work, centre = self.workflow, list(self.lift_end)
        work.held = self.held

        def plan():
            with self.geometry():
                return work.build_shake(dict(success=True, limits=limits, q_after_rad=centre))[0]

        self.shake_future = self.pool.submit(plan)

    def unchanged(self):
        """Files are re-hashed only when their metadata changed (the original cached digests)."""
        for path, (signature, digest) in self.fingerprints.items():
            current = stamp(path)
            if current != signature:
                if file_hash(path) != digest:
                    raise RuntimeError("algorithm/model/calibration/config changed; stop and rebuild deployment")
                self.fingerprints[path] = (current, digest)

    def ready(self):
        """Wait for the background startup (camera, model, collision geometry); a no-op once warm."""
        self.warm_up()
        vision = self.workflow._vision
        vision.camera_future.result(timeout=15)  # The original VisionResources.capture bounds.
        vision.model_future.result(timeout=30)
        self.geometry_ready.result(timeout=self.cfg["timeout_s"])

    def prepare(self):
        self.unchanged()
        self.ready()
        with self.geometry():
            self.workflow.capture()
            self.workflow.plan()

    def speed_percent(self, phase):
        """FAST speed: fast_phase_speed_percent per phase, otherwise fast_speed_percent."""
        return self.g.get("fast_phase_speed_percent", {}).get(phase, self.g.get("fast_speed_percent", 100))

    @staticmethod
    def controller_limits(state):
        limits = state.get("controller_limits")
        if not limits or [row["joint"] for row in limits] != list(range(1, 8)):
            raise RuntimeError("controller joint limits unavailable; FAST profiles are planned from them")
        return limits

    def transition(self, start, stages, speed_percent, limits, options=None):
        """Synchronized rest-to-rest profile per stage (trapezoid or quintic), as joint_delivery.move_js
        streams it."""
        options = options or self.options
        budget, cap = options["limit_utilization"], options["velocity_cap_deg_s"]
        velocity, acceleration = [], []
        for row in limits:
            speed = row["max_velocity_rad_s"] * speed_percent / 100 * budget
            velocity.append(speed if cap is None else min(speed, math.radians(cap)))
            acceleration.append(min(row["max_acceleration_rad_s2"], options["acceleration_cap_rad_s2"]) * budget)
        times, knots, elapsed, peak = [0.0], [list(start)], 0.0, 0.0
        for target in stages:
            begin = knots[-1]
            if options["profile"] == "trapezoid":
                duration, ramp, normalized = self.delivery.trapezoid_profile(begin, target, velocity, acceleration)
                position = lambda t: self.delivery.trapezoid_position(t, duration, ramp, normalized)  # noqa: E731
            else:  # Quintic: u = 10t^3 - 15t^4 + 6t^5 over smooth_duration.
                duration = self.delivery.smooth_duration(begin, target, velocity, acceleration)
                normalized = 1.875 / duration
                position = lambda t: (lambda x: 10 * x**3 - 15 * x**4 + 6 * x**5)(min(1.0, t / duration))  # noqa: E731
            peak = max(peak, normalized * max(abs(b - a) for a, b in zip(begin, target)))
            count = max(1, math.ceil(duration * KNOT_HZ))
            for i in range(1, count + 1):
                u = position(duration * i / count)
                knots.append(list(target) if i == count else [a + (b - a) * u for a, b in zip(begin, target)])
                times.append(elapsed + duration * i / count)
            elapsed += duration
        # The original sample period is min(20 ms, 0.5 deg / peak speed).
        rate = min(500.0, max(50.0, peak / STREAM_STEP_RAD))
        # FAST completion: hand over once the last target is sent; the arm settles meanwhile.
        return dict(
            kind="trajectory",
            times_s=times,
            positions_rad=knots,
            command_rate_hz=rate,
            max_step_rad=COMMAND_STEP_RAD,
            speed_scale=speed_percent / 100,
            tolerance_rad=self.settled_rad,
            wait_for_arrival=False,
        )

    def shake(self, start, limits):
        """The joint-shake recipe around the lift endpoint (prepared during the grip, or planned now as
        build_shake does), streamed once the arm has settled there (shake_start_tolerance_deg)."""
        work = self.workflow
        work.held = self.held
        centre = list(self.lift_end) if self.lift_end is not None else list(start)
        plan = None
        if self.shake_future is not None:
            plan, self.shake_future = self.shake_future.result(timeout=self.cfg["timeout_s"]), None
        if plan is None or plan["start_q_rad"] != centre:
            plan, _ = work.build_shake(dict(success=True, limits=limits, q_after_rad=centre))
        tolerance = math.radians(self.g.get("shake_start_tolerance_deg", 0.5))
        deadline = time.monotonic() + SHAKE_SETTLE_S
        while True:
            current = self.state()
            if max(abs(a - b) for a, b in zip(current["joints_rad"], centre)) <= tolerance:
                break
            if not current["moving"] or time.monotonic() > deadline:
                # Settled elsewhere: re-read and re-check the shake from the real pose (original recovery).
                centre = list(current["joints_rad"])
                plan, _ = work.build_shake(dict(success=True, limits=limits, q_after_rad=centre))
                break
            time.sleep(0.01)
        start = centre
        parameters = plan["parameters"]
        rate = parameters["command_rate_hz"] or 200
        count = math.ceil(plan["duration_s"] * rate)
        commands = [self.profile.command_values(plan, plan["duration_s"] * i / count) for i in range(count + 1)]
        # The first command is sent one tick after the arm's position, as the original streamer did.
        times = [0.0] + [1 / rate + plan["duration_s"] * i / count for i in range(count + 1)]
        commands[-1] = list(start)
        return dict(
            kind="trajectory",
            times_s=times,
            positions_rad=[list(start)] + commands,
            command_rate_hz=rate,
            max_step_rad=math.radians(parameters["command_step_deg"]),
            speed_scale=parameters["controller_speed_percent"] / 100,
            tolerance_rad=self.settled_rad,
            wait_for_arrival=False,
        )

    def gesture(self, name, state):
        """A result-feedback gesture, or the original "home" action, as scripts/result_feedback.py runs it
        (feedback_execution): the arm to the recipe pose at the recipe speed on the configured profile,
        checked against the HOME table scene, with the hand targets sent on schedule from the first arm
        command (together), after it (arm_then_hand) or before it (hand_then_arm)."""
        self.unchanged()
        if self.registry is None:
            registry = importlib.import_module("scripts.action_registry").load_registry(
                self.root / "configs/actions/gestures"
            )
            if registry.errors:
                raise ValueError("; ".join(registry.errors))
            self.registry = registry
        recipe = self.registry.recipe(name)  # win/lose/draw are aliases of yeah/thumbs-up/tie.
        start, limits = state["joints_rad"], self.controller_limits(state)
        target = [math.radians(value) for value in recipe["joints_deg"]]
        self.ensure_geometry()
        with self.geometry():
            route = self.module.arm_plan(start, [target], self.workflow.table_scene, self.cfg)
        if route["blockers"]:
            raise RuntimeError(str(route["blockers"]))
        motion = self.transition(
            start,
            [stage["target_q_rad"] for stage in route["stages"]],
            recipe["speed_percent"],
            limits,
            self.gesture_options,
        )
        maximum = recipe["finger_speed_mode"] == "max"
        wait = recipe["finger_max_wait_s"] if maximum else recipe["finger_duration_s"]
        sequence = importlib.import_module("cup_grasp_demo.flow.feedback_sequence")
        poses, interval = sequence.sequence_values(recipe.get("hand_sequence"), recipe["hand_0_100"], wait)
        mode, delay = recipe["execution"]["mode"], recipe["execution"]["delay_s"]
        hand = (len(poses) - 1) * interval + wait
        first = {"together": delay, "arm_then_hand": motion["times_s"][-1] + delay}.get(mode, 0.0)
        if mode == "hand_then_arm":  # The arm holds its start until the hand has finished.
            offset = hand + delay
            motion["times_s"] = [0.0] + [offset + t for t in motion["times_s"]]
            motion["positions_rad"] = [list(start)] + motion["positions_rad"]
        execution = FINGER_MAX_SPEED_S if maximum else wait
        motion["effector_schedule"] = [
            (first + i * interval, [value / 100 for value in pose], execution) for i, pose in enumerate(poses)
        ]
        motion["hold_s"] = wait - execution  # The original waits the whole finger time after the last target.
        motion["hand_open"] = all(value == 0 for value in poses[-1])
        return motion

    def motions(self, phase, state):
        """The deliveries of one phase, in order, as the original FAST executor issued them."""
        with self.geometry():
            return self._motions(phase, state)

    def _motions(self, phase, state):
        start, limits = state["joints_rad"], self.controller_limits(state)
        if phase == "shake":
            self.unchanged()
            return [self.shake(start, limits)]
        stages = self.targets(phase, state)
        if phase == "approach":
            self.start_following(stages[-1])
        if phase == "lift":
            self.start_shake(limits)
        if phase == "lower" and self.g.get("lower_command_mode") == "controller_endpoint":
            # Controller-planned move_j per stage at the phase speed, the same target re-sent every
            # 50 ms while beyond 0.5 deg, complete on two samples within it (_controller_endpoint).
            return [
                dict(
                    kind="point",
                    target=target,
                    speed_scale=self.speed_percent("lower") / 100,
                    tolerance_rad=self.settled_rad,
                    wait_for_arrival=False,
                    resend_interval_s=ENDPOINT_RESEND_S,
                )
                for target in stages
            ]
        return [self.transition(start, stages, self.speed_percent(phase), limits)]

    def targets(self, phase, state):
        """Joint targets of a phase and their checked path, as green_pipeline.Workflow.perform plans them."""
        self.unchanged()
        work = self.workflow
        start = state["joints_rad"]
        held, margin = None, 0
        if phase == "approach":
            if time.time() - work.capture_time > min(30, self.cfg["plan_max_age_s"]):
                raise RuntimeError("captured cup scene expired")
            targets = work.approach_targets
            # plan() checked this route from HOME; reused from an unchanged start (Workflow.move).
            route = work._prepared.take(
                "approach", start, targets, work.scene, start_tolerance_deg=min(0.05, self.cfg["start_tolerance_deg"])
            )
            if route is not None:
                return [stage["target_q_rad"] for stage in route["stages"]]
        elif phase == "lift":
            targets = None
            if self.following is not None:
                seed, prepared = self.following.result(timeout=self.cfg["timeout_s"])
                self.following = None
                lift_seed_close = importlib.import_module("cup_grasp_demo.flow.green_prepared").lift_seed_close
                if lift_seed_close(seed, start, work.kin, work.tcp):
                    targets = prepared  # The IK endpoint only; the path is checked from the real start.
            self.place = list(start)
            self.held = work.held_geometry(start)
            held, margin = self.held, -self.g["place_tolerance_mm"]
            if targets is None:
                targets = work.vertical("lift", start, self.g["lift_mm"] / 1000, single_target=True)
            self.lift_end = list(targets[-1])
        elif phase == "lower":
            held, margin = self.held, -self.g["place_tolerance_mm"]
            targets = work.place_targets(self.place)  # The grasp pose itself without a place offset.
            self.lower_target = targets[-1]
        elif phase == "return_home":
            targets = [self.home]
            if not self.g.get("direct_return_home", False):
                targets = (
                    work.vertical("retreat", start, self.g["retreat_clearance_mm"] / 1000, single_target=True) + targets
                )
        else:
            raise ValueError("unsupported visual planner phase")
        route = self.module.arm_plan(start, targets, work.scene, self.cfg, held=held, cup_margin_mm=margin)
        if route["blockers"]:
            raise RuntimeError(str(route["blockers"]))
        return [stage["target_q_rad"] for stage in route["stages"]]

    def verify_lower(self, state):
        """Placement arrival as the original checks it; returns a note when only recorded."""
        actual = self.workflow.kin.forward(state["joints_rad"])[0] @ self.workflow.tcp
        target = self.workflow.kin.forward(self.lower_target)[0] @ self.workflow.tcp
        error_mm = float(self.np.linalg.norm(actual[:3, 3] - target[:3, 3])) * 1000
        tolerance = self.g.get("place_arrival_tolerance_mm", self.g["place_tolerance_mm"])
        if error_mm <= tolerance:
            return None
        if self.g.get("precision_error_action", "stop") != "record":
            raise RuntimeError(f"placement error {error_mm:.2f} mm; keep hand closed, no release/retry")
        return f"placement error {error_mm:.2f} mm above {tolerance} mm; recorded, releasing as configured"

    def close(self):
        self.pool.shutdown(wait=True, cancel_futures=True)
        if self.workflow._vision is not None:
            self.workflow._vision.close()
            self.workflow._vision = None
