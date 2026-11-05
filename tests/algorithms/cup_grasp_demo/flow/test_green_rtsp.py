# Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
# SPDX-License-Identifier: Apache-2.0
"""Optional RTSP preview failures never require a camera or robot connection."""

import io
import socket
import threading
import time
import unittest
from unittest.mock import MagicMock, Mock, patch

from cup_grasp_demo.flow import green_rtsp as rtsp


class RtspStreamerTests(unittest.TestCase):
    def start_patch(self, patcher):
        self.addCleanup(patcher.stop)
        return patcher.start()

    def setUp(self):
        self.thread = self.start_patch(patch.object(rtsp.threading, "Thread"))
        self.clock = self.start_patch(patch.object(rtsp.time, "monotonic", return_value=0.0))
        self.popen = self.start_patch(patch.object(rtsp.subprocess, "Popen"))
        self.socket = self.start_patch(patch("socket.create_connection"))
        self.process = Mock(stdin=io.BytesIO())
        self.process.poll.return_value = None
        self.popen.return_value = self.process
        self.streamer = rtsp.RtspStreamer("127.0.0.1", 8554, "/dice/seg", 640, 480, 6)
        self.addCleanup(self.streamer.close)

    def test_missing_server_does_not_spawn_and_warns_once(self):
        self.socket.side_effect = ConnectionRefusedError("video server unavailable")
        with self.assertLogs(rtsp.__name__, level="WARNING") as logs:
            self.assertFalse(self.streamer._ensure_running())
            self.clock.return_value = 4.9
            self.assertFalse(self.streamer._ensure_running())
            self.clock.return_value = 5.0
            self.assertFalse(self.streamer._ensure_running())
        self.assertEqual(self.socket.call_count, 2)
        self.popen.assert_not_called()
        self.assertEqual(len(logs.output), 1)
        self.assertIn("preview unavailable", logs.output[0])
        self.assertIn("video server unavailable", self.streamer.last_error)

    def test_server_recovery_starts_unchanged_pipeline(self):
        self.socket.side_effect = [ConnectionRefusedError("offline"), MagicMock()]
        with self.assertLogs(rtsp.__name__, level="WARNING"):
            self.assertFalse(self.streamer._ensure_running())
        self.clock.return_value = 5.0
        self.assertTrue(self.streamer._ensure_running())
        self.assertTrue(self.streamer._ensure_running())
        self.assertEqual(self.socket.call_count, 2)
        self.popen.assert_called_once()
        command = self.popen.call_args.args[0]
        self.assertEqual(command, self.streamer.command())
        self.assertIn("location=rtsp://127.0.0.1:8554/dice/seg", command)
        self.assertIn("protocols=tcp", command)
        self.assertIn("format=nv12", command)
        self.assertIsNone(self.popen.call_args.kwargs["stderr"])

    def test_child_exit_obeys_backoff_before_restart(self):
        self.assertTrue(self.streamer._ensure_running())
        self.process.poll.return_value = 1
        self.clock.return_value = 1.0
        self.assertFalse(self.streamer._ensure_running())
        self.clock.return_value = 5.9
        self.assertFalse(self.streamer._ensure_running())
        self.popen.assert_called_once()
        replacement = Mock(stdin=io.BytesIO())
        replacement.poll.return_value = None
        self.popen.return_value = replacement
        self.clock.return_value = 6.0
        self.assertTrue(self.streamer._ensure_running())
        self.assertEqual(self.popen.call_count, 2)
        self.assertEqual(self.streamer.restarts(), 1)

    def test_spawn_failure_obeys_backoff(self):
        self.popen.side_effect = FileNotFoundError("gst-launch-1.0")
        with self.assertLogs(rtsp.__name__, level="WARNING") as logs:
            self.assertFalse(self.streamer._ensure_running())
            self.clock.return_value = 4.9
            self.assertFalse(self.streamer._ensure_running())
            self.clock.return_value = 5.0
            self.assertFalse(self.streamer._ensure_running())
        self.assertEqual(self.popen.call_count, 2)
        self.assertEqual(self.socket.call_count, 2)
        self.assertEqual(len(logs.output), 1)

    def test_broken_pipe_sets_retry_deadline(self):
        self.process.stdin = Mock()
        self.process.stdin.write.side_effect = BrokenPipeError("publisher stopped")
        self.streamer._slot = b"frame"
        calls = 0

        def wake(**kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                self.streamer._stopped.set()

        self.streamer._wakeup = Mock()
        self.streamer._wakeup.wait.side_effect = wake
        self.streamer._writer_loop()
        self.assertIn("publisher stopped", self.streamer.last_error)
        self.assertEqual(self.streamer._restart_not_before, 5.0)
        self.streamer._stopped.clear()
        self.clock.return_value = 4.9
        self.assertFalse(self.streamer._ensure_running())
        self.popen.assert_called_once()

    def test_closed_server_drops_only_preview_frame(self):
        self.socket.side_effect = ConnectionRefusedError("offline")
        self.streamer._slot = b"frame"
        calls = 0

        def wake(**kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                self.streamer._stopped.set()

        self.streamer._wakeup = Mock()
        self.streamer._wakeup.wait.side_effect = wake
        with self.assertLogs(rtsp.__name__, level="WARNING"):
            self.streamer._writer_loop()
        self.assertEqual((self.streamer.sent, self.streamer.dropped), (0, 1))
        self.popen.assert_not_called()

    def test_close_during_probe_prevents_late_child_start(self):
        def probe(*args, **kwargs):
            self.streamer._stopped.set()
            return MagicMock()

        self.socket.side_effect = probe
        self.assertFalse(self.streamer._ensure_running())
        self.popen.assert_not_called()

    def test_closed_streamer_never_probes_or_starts(self):
        self.streamer.close()
        self.assertFalse(self.streamer._ensure_running())
        self.socket.assert_not_called()
        self.popen.assert_not_called()


class RtspOfflineIntegrationTests(unittest.TestCase):
    def test_real_writer_waits_for_server_then_resumes(self):
        process = Mock(stdin=io.BytesIO())
        process.poll.return_value = None
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
            with (
                patch.object(rtsp.subprocess, "Popen", return_value=process) as launch,
                self.assertLogs(rtsp.__name__, level="WARNING") as logs,
            ):
                streamer = rtsp.RtspStreamer(
                    "127.0.0.1", port, "/preview", 2, 2, 6, restart_backoff_s=0.01
                )
                try:
                    deadline = time.monotonic() + 3
                    while streamer.dropped < 2 and time.monotonic() < deadline:
                        streamer.submit(b"frame")
                        threading.Event().wait(0.02)
                    self.assertGreaterEqual(streamer.dropped, 2)
                    self.assertTrue(streamer._thread.is_alive())
                    launch.assert_not_called()
                    listener.listen(1)
                    deadline = time.monotonic() + 3
                    while streamer.sent == 0 and time.monotonic() < deadline:
                        streamer.submit(b"frame")
                        threading.Event().wait(0.02)
                    self.assertGreater(streamer.sent, 0)
                    launch.assert_called_once()
                finally:
                    streamer.close()
                self.assertFalse(streamer._thread.is_alive())
                self.assertEqual(len(logs.output), 1)


if __name__ == "__main__":
    unittest.main()
