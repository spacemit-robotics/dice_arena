#!/usr/bin/env python3
# Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
# SPDX-License-Identifier: Apache-2.0
"""Check TTS readiness, startup cleanup and reuse without loading a model or opening a port."""

import contextlib
import importlib.util
import io
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np


def check(game, daemon):
    with tempfile.TemporaryDirectory(prefix="dice-tts-startup-") as temporary:
        root = Path(temporary)
        (root / "src").mkdir()
        (root / "browser_poc_manifest.json").write_text("{}", encoding="utf-8")
        reference = root / "reference.wav"
        reference.touch()

        def make_runtime(**overrides):
            settings = dict(
                root=root,
                model_dir=root,
                voice="Junhao",
                reference_audio=reference,
                max_new_frames=120,
                voice_clone_max_text_tokens=24,
                first_chunk_text_tokens=16,
                warmup_text="",
                seed=1234,
            )
            settings.update(overrides)
            return daemon.MossRuntime(**settings)

        def backend_factory():
            backend = Mock()
            backend.codec_meta = {"codec_config": {"sample_rate": 48000, "channels": 2}}
            backend.sessions = {
                "decode": SimpleNamespace(
                    get_inputs=lambda: [SimpleNamespace(name="past_key_0", shape=[None, "capacity"])]
                )
            }
            backend.warmup.side_effect = AssertionError("duplicate warmup")
            backend.synthesize.return_value = dict(
                waveform=np.ones((64, 2), dtype=np.float32), chunk_results=[dict(stop_reason="audio_end")]
            )
            backend.resolve_prompt_audio_codes.return_value = [[1] * 16]
            return backend

        backend = backend_factory()
        constructor = Mock(return_value=backend)
        with (
            patch.dict(sys.modules, onnx_tts_runtime=SimpleNamespace(OnnxTtsRuntime=constructor)),
            patch.object(daemon.MossRuntime, "_configure_external_runtime"),
            patch.object(daemon, "_rebind_ep_threads"),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            runtime = make_runtime()
            assert runtime.health()["startup_phase"] == "pending"

            def synthesize(**kwargs):
                assert not runtime.health()["ready"]
                try:
                    runtime._require_runtime()
                except daemon.MossRuntimeError:
                    pass
                else:
                    raise AssertionError("runtime became usable before synthesis validation")
                return dict(waveform=np.ones((64, 2), dtype=np.float32), chunk_results=[dict(stop_reason="audio_end")])

            backend.synthesize.side_effect = synthesize
            runtime._initialize()
            health = runtime.health()
            assert health["ready"] and health["startup_phase"] == "ready", health
            assert set(health["startup_timings_seconds"]) == {
                "runtime_import",
                "model_load",
                "voice_prepare",
                "synthesis_warmup",
                "total",
            }
            assert health["sample_rate"] == 48000 and health["channels"] == 2
            backend.warmup.assert_not_called()
            call = backend.synthesize.call_args.kwargs
            assert call["text"] == "你好。" and call["seed"] == 1234
            assert call["max_new_frames"] == 120 and not call["write_wav"]
            assert not call["enable_normalize_tts_text"] and not call["enable_wetext"]
            assert constructor.call_args.kwargs["execution_provider"] == "spacemit"
            assert runtime._require_runtime()[0] is backend
            backend.synthesize.side_effect = None
            custom = make_runtime(warmup_text="自定义预热。")
            custom._initialize()
            assert backend.synthesize.call_args.kwargs["text"] == "自定义预热。"
            for waveform, reason in (
                (np.empty((0, 2)), "audio_end"),
                (np.full((2, 2), np.nan), "audio_end"),
                (np.ones((2, 2)), "max_frames"),
            ):
                backend.synthesize.return_value = dict(waveform=waveform, chunk_results=[dict(stop_reason=reason)])
                failed = make_runtime()
                failed._initialize()
                assert not failed.ready and not failed.starting and failed.error
                assert failed.health()["startup_phase"] == "synthesis_warmup"
            constructor.side_effect = RuntimeError("model load failed")
            failed = make_runtime()
            failed._initialize()
            assert not failed.ready and "model load failed" in failed.error

        spec = importlib.util.spec_from_file_location(
            "dice_moss_launcher", game / "backend/components/tts_moss_nano/launcher.py"
        )
        launcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(launcher)
        settings = SimpleNamespace(start_timeout_seconds=1, base_url="http://127.0.0.1:18082")
        pid_file = root / "daemon.pid"
        log_file = root / "daemon.log"
        for scenario in ("ready", "failed", "timeout", "interrupt", "exited", "kill"):
            process = Mock(pid=123)
            process.poll.return_value = 1 if scenario == "exited" else None
            if scenario == "kill":
                process.wait.side_effect = [subprocess.TimeoutExpired("daemon", 3), 0]
            pid_file.write_text("123\n", encoding="utf-8")
            clock = [0.0]

            def sleep(seconds):
                clock[0] += seconds

            responses = (
                [None, {"starting": True, "startup_phase": "model_load"}, {"ready": True}]
                if scenario == "ready"
                else None
            )
            with (
                patch.object(launcher.time, "monotonic", side_effect=lambda: clock[0]),
                patch.object(launcher.time, "sleep", side_effect=sleep),
                patch.object(launcher, "_health") as health,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                if responses:
                    health.side_effect = responses
                elif scenario == "interrupt":
                    health.side_effect = KeyboardInterrupt()
                else:
                    health.return_value = (
                        {"error": "broken model", "starting": False} if scenario in ("failed", "kill") else None
                    )
                try:
                    launcher._finish_start(process, settings, pid_file, log_file)
                except (SystemExit, KeyboardInterrupt):
                    assert scenario != "ready"
                else:
                    assert scenario == "ready"
            if scenario == "ready":
                process.terminate.assert_not_called()
                assert pid_file.is_file()
            else:
                assert not pid_file.exists()
                if scenario != "exited":
                    process.terminate.assert_called_once()
                if scenario == "kill":
                    process.kill.assert_called_once()
            assert clock[0] <= settings.start_timeout_seconds

        settings = SimpleNamespace(
            root=root, model_dir=root, reference_audio=reference, base_url="http://127.0.0.1:18082"
        )
        pid_file.write_text("123\n", encoding="utf-8")
        with (
            patch.object(launcher, "load_settings", return_value=settings),
            patch.object(launcher, "_paths", return_value=(pid_file, log_file)),
            patch.object(launcher, "_is_expected", return_value=True),
            patch.object(launcher, "_discover", return_value=[]),
            patch.object(launcher, "_health", return_value={"ready": True}),
            patch.object(launcher.subprocess, "Popen") as spawn,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            assert launcher.start() == 0
            spawn.assert_not_called()
