#!/usr/bin/env bash
# Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
# SPDX-License-Identifier: Apache-2.0
# Calibration web page, default http://127.0.0.1:8091 (--host 0.0.0.0 for the LAN). See calibrate.sh.
set -euo pipefail
APP="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$APP/tools/calibration_env.sh"
exec "${PYTHON:-python3}" -m calibration.web.server "$@"
