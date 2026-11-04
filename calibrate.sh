#!/usr/bin/env bash
# Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
# SPDX-License-Identifier: Apache-2.0
# Hand-eye calibration commands (first/window/plan/auto/solve/register/restore/apply/table/status)
# of the dice-arena application. Configuration and resources are in
# calibration/config and calibration/trajectories; data goes to the manipulation site directory.
# The arm and hand are reached only through the installed framework (MANIPULATION_PREFIX).
set -euo pipefail
APP="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$APP/tools/calibration_env.sh"
exec "${PYTHON:-python3}" "$APP/calibration/workflow.py" "$@"
