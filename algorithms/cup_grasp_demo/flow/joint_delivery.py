# Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
# SPDX-License-Identifier: Apache-2.0
"""Joint delivery options and rest-to-rest timing profiles."""

import math


def delivery_options(raw=None):
    """Keep legacy defaults; the release config explicitly selects full budget."""
    options = dict(
        start_drift_tolerance_deg=0.1,
        endpoint_resend_interval_s=0.0,
        command_mode="smooth_profile",
        limit_utilization=0.97,
        acceleration_cap_rad_s2=5.0,
        tracking_error_deg=5.0,
        tracking_error_action="stop",
        envelope_margin_deg=5.0,
        velocity_cap_deg_s=50.0,
        profile="quintic",
        feedback_freshness_limit_s=0.1,
        limits_read_timeout_s=0.5,
        limits_read_retries=1,
        cache_live_limits=False,
        scheduling_gap_limit_s=0.08,
        endpoint_blend=0.2,
        endpoint_lead_max_deg=0.5,
    )
    raw = raw or {}
    if not isinstance(raw, dict) or set(raw) - set(options):
        raise ValueError("Invalid joint_delivery options")
    options.update(raw)
    if options["command_mode"] not in ("smooth_profile", "controller_endpoint", "bounded_blend"):
        raise ValueError("Invalid joint_delivery.command_mode")
    interval = options["endpoint_resend_interval_s"]
    if (
        isinstance(interval, bool)
        or not isinstance(interval, (int, float))
        or not math.isfinite(interval)
        or not (interval == 0 or 0.02 <= interval <= 0.2)
    ):
        raise ValueError("endpoint_resend_interval_s must be 0 or 0.02..0.2")
    if options["profile"] not in ("quintic", "trapezoid"):
        raise ValueError("joint_delivery.profile must be quintic or trapezoid")
    for name, low, high in (
        ("start_drift_tolerance_deg", 0.1, 0.5),
        ("endpoint_blend", 0.0, 0.2),
        ("endpoint_lead_max_deg", 0.0, 1.0),
        ("limit_utilization", 0.1, 1.0),
        ("acceleration_cap_rad_s2", 0.1, 5.0),
        ("tracking_error_deg", 0.1, 10.0),
        ("envelope_margin_deg", 0.1, 10.0),
        ("feedback_freshness_limit_s", 0.1, 0.5),
        ("limits_read_timeout_s", 0.1, 5.0),
        ("scheduling_gap_limit_s", 0.08, 0.5),
    ):
        value = options[name]
        if (
            isinstance(value, bool)
            or not isinstance(value, (float, int))
            or not math.isfinite(value)
            or not low <= value <= high
        ):
            raise ValueError(f"joint_delivery.{name} must be {low}..{high}")
    cap = options["velocity_cap_deg_s"]
    if cap is not None and (
        isinstance(cap, bool) or not isinstance(cap, (int, float)) or not math.isfinite(cap) or cap <= 0
    ):
        raise ValueError("joint_delivery.velocity_cap_deg_s must be positive or null")
    if options["tracking_error_action"] not in ("record", "stop"):
        raise ValueError("joint_delivery.tracking_error_action must be record or stop")
    retries = options["limits_read_retries"]
    if isinstance(retries, bool) or not isinstance(retries, int) or not 0 <= retries <= 5:
        raise ValueError("joint_delivery.limits_read_retries must be an integer from 0 to 5")
    if type(options["cache_live_limits"]) is not bool:
        raise ValueError("joint_delivery.cache_live_limits must be boolean")
    return options


def smooth_duration(start, target, velocity, acceleration):
    """Quintic rest-to-rest path: peak normalized speed 1.875, accel 10/sqrt(3)."""
    return max(
        0.04,
        *[
            max(
                1.875 * abs(b - a) / v,
                math.sqrt((10 / math.sqrt(3)) * abs(b - a) / acc),
            )
            for a, b, v, acc in zip(start, target, velocity, acceleration)
        ],
    )


def trapezoid_profile(start, target, velocity, acceleration):
    """Synchronized rest-to-rest motion, bounded by every moving joint.

    Return duration, acceleration interval and normalized peak velocity.
    Zero-distance paths retain a short constant-position delivery interval.
    """
    moving = [(abs(b - a), v, acc) for a, b, v, acc in zip(start, target, velocity, acceleration) if abs(b - a) > 1e-12]
    if not moving:
        return 0.04, 0.02, 0.0
    vmax = min(v / distance for distance, v, _ in moving)
    amax = min(acc / distance for distance, _, acc in moving)
    peak = min(vmax, math.sqrt(amax))
    ramp = peak / amax
    duration = 1 / peak + ramp
    scale = max(1.0, 0.04 / duration)
    return duration * scale, ramp * scale, peak / scale


def trapezoid_position(elapsed, duration, ramp, peak):
    if peak == 0:
        return min(1.0, max(0.0, elapsed / duration))
    elapsed = min(duration, max(0.0, elapsed))
    if elapsed < ramp:
        return 0.5 * peak / ramp * elapsed**2
    if elapsed > duration - ramp:
        return 1 - 0.5 * peak / ramp * (duration - elapsed) ** 2
    return peak * (elapsed - 0.5 * ramp)
