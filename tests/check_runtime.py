#!/usr/bin/env python3
# Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
# SPDX-License-Identifier: Apache-2.0
"""Check installed lifecycle entry points without starting audio, cameras or device control."""

import argparse
import contextlib
import errno
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from check_tts_startup import check as check_tts_startup


def check(game):
    game = Path(game).resolve()
    sys.path.insert(0, str(game / "backend"))
    spec = importlib.util.spec_from_file_location("dice_componentctl", game / "backend/componentctl.py")
    control = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(control)
    manifest = json.loads((game / "backend/components/tts_moss_nano/manifest.json").read_text())
    with tempfile.TemporaryDirectory(prefix="dice-runtime-") as temporary:
        # The actual shell entry points run, but their Python delegate is replaced by an argument
        # recorder. The TTS daemon and its model are never loaded.
        interpreter = Path(temporary) / "python recorder"
        interpreter.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n', encoding="utf-8")
        interpreter.chmod(0o700)
        environment = dict(os.environ, DICE_PYTHON=str(interpreter))
        for action in ("start", "stop"):
            command = control._command_for(manifest, action)
            assert command and os.access(command[0], os.X_OK), f"not executable: {command}"
            result = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=5, check=True)
            assert result.stdout.splitlines() == [str(game / "backend/components/tts_moss_nano/launcher.py"), action], (
                result.stdout
            )
    for error, expected in (
        (PermissionError(errno.EACCES, "permission denied"), 126),
        (FileNotFoundError(errno.ENOENT, "file not found"), 127),
    ):
        with (
            patch.object(control.subprocess, "run", side_effect=error),
            contextlib.redirect_stderr(io.StringIO()) as diagnostic,
        ):
            assert control._run_lifecycle(["unavailable"], "tts_moss_nano", "start") == expected
        assert "cannot start" in diagnostic.getvalue() and "Traceback" not in diagnostic.getvalue()
    spec = importlib.util.spec_from_file_location(
        "dice_moss_daemon", game / "backend/components/tts_moss_nano/daemon.py"
    )
    daemon = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(daemon)  # Imports the bridge only, never its model or server.
    with (
        tempfile.TemporaryDirectory(prefix="dice-tts-layout-") as temporary,
        patch.dict(os.environ),
        patch.object(sys, "path", list(sys.path)),
    ):
        root = Path(temporary)
        (root / "src").mkdir()
        runtime = SimpleNamespace(
            root=root,
            ep_intra_thread_num=1,
            ep_inter_thread_num=1,
            ep_intra_thread_affinity="",
            ep_disable_op_type_filter="",
        )
        daemon.MossRuntime._configure_external_runtime(runtime)
        assert str(root / "src") in sys.path
        assert str(root / "python") not in sys.path
        (root / "python").mkdir()
        (root / "lib").mkdir()
        daemon.MossRuntime._configure_external_runtime(runtime)
        assert str(root / "python") in sys.path
        assert str(root / "lib") in os.environ["LD_LIBRARY_PATH"].split(os.pathsep)
        runtime.root = root / "missing"
        try:
            daemon.MossRuntime._configure_external_runtime(runtime)
        except daemon.MossRuntimeError as error:
            assert "source directory is missing" in str(error)
        else:
            raise AssertionError("missing runtime sources were accepted")
    check_tts_startup(game, daemon)
    print(
        json.dumps(
            dict(
                lifecycle_permissions="passed",
                lifecycle_errors="passed",
                tts_runtime_layouts="passed",
                tts_startup="passed",
            )
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("game", type=Path)
    check(parser.parse_args().game)
