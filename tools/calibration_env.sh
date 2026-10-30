#!/usr/bin/env bash
# Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
# SPDX-License-Identifier: Apache-2.0
# Locate the framework from a source checkout or a relocated installation; opens no devices.
APP="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -z "${MANIPULATION_PREFIX:-${PREFIX:-}}" ]]; then
    calibration_prefix="$APP"
    while [[ "$calibration_prefix" != / && ! -f "$calibration_prefix/.spacemit-manipulation.json" ]]; do
        calibration_prefix="$(dirname -- "$calibration_prefix")"
    done
    if [[ -f "$calibration_prefix/.spacemit-manipulation.json" ]]; then
        export MANIPULATION_PREFIX="$calibration_prefix"
    else
        MANIPULATION_PREFIX="$(cd -- "$APP/../../.." && pwd)/output/staging"
        export MANIPULATION_PREFIX
    fi
else
    export MANIPULATION_PREFIX="${MANIPULATION_PREFIX:-$PREFIX}"
fi
export PYTHONPATH="$APP${PYTHONPATH:+:$PYTHONPATH}" PYTHONNOUSERSITE=1 OPENBLAS_NUM_THREADS=1
cd "$APP" || return
