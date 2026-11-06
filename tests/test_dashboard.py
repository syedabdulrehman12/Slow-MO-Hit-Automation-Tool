from io import StringIO
import json
import subprocess
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import Mock, patch

from dashboard import VENV_PYTHON, DashboardService, make_handler


class DashboardHttpTests(unittest.TestCase):
    def setUp(self):
        self.service = DashboardService()
        self.server = ThreadingHTTPServer(
            ("127.0.0.1", 0), make_handler(self.service))
        self.server.daemon_threads = True
        self.server_thread = threading.Thread(
            target=self.server.serve_forever, daemon=True)
        self.server_thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.service.close()
        self.server_thread.join(timeout=2)

    def test_page_contains_only_the_test_button_and_status(self):
        with urlopen(self.base_url + "/") as response:
            page = response.read().decode("utf-8")

        self.assertIn("Start test", page)
        self.assertEqual(page.count("<button"), 2)
        self.assertIn('id="stop" disabled>Stop test</button>', page)
        self.assertNotIn("/stream", page)
        self.assertNotIn("screencap", page)
        self.assertNotIn("Live device screen", page)

    def test_start_button_runs_default_agent_command(self):
        process = Mock()
        process.poll.return_value = None
        process.wait.return_value = 0
        process.stdout = StringIO("monkey output\n")
        with patch("dashboard.subprocess.Popen", return_value=process) as popen:
            request = Request(
                self.base_url + "/api/start", data=b"", method="POST")
            with urlopen(request, timeout=5) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(json.loads(response.read()), {"ok": True})

        args, kwargs = popen.call_args
        command = args[0]
        self.assertEqual(command[0], str(VENV_PYTHON))
        self.assertEqual(command[1:3], ["-u", "-c"])
        self.assertEqual(
            command[3],
            "from slowmo_qa.runner import run_suite; "
            "raise SystemExit(run_suite('monkey'))",
        )
        self.assertEqual(kwargs["stdout"], subprocess.PIPE)
        self.assertEqual(kwargs["stderr"], subprocess.STDOUT)
        self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)

    def test_state_endpoint_reports_ready(self):
        with urlopen(self.base_url + "/api/state") as response:
            state = json.loads(response.read())

        self.assertFalse(state["test_running"])
        self.assertEqual(state["status"], "Ready")

    def test_stop_endpoint_terminates_running_test(self):
        process = Mock()
        process.poll.return_value = None
        self.service._agent = process

        request = Request(
            self.base_url + "/api/stop", data=b"", method="POST")
        with urlopen(request, timeout=5) as response:
            result = json.loads(response.read())

        self.assertEqual(result, {"ok": True, "stopping": True})
        process.terminate.assert_called_once_with()
        self.assertTrue(self.service.state()["stopping"])

    def test_state_endpoint_returns_incremental_test_logs(self):
        self.service.append_log("Monkey run started\n")
        self.service.append_log("Action succeeded\n")

        with urlopen(self.base_url + "/api/state?after=1") as response:
            state = json.loads(response.read())

        self.assertEqual(state["logs"], [{"id": 2, "text": "Action succeeded\n"}])

    def test_old_screen_stream_route_is_removed(self):
        try:
            urlopen(self.base_url + "/stream")
        except HTTPError as exc:
            exc.close()
            self.assertEqual(exc.code, 404)
        else:
            self.fail("Screen stream route should not exist")


if __name__ == "__main__":
    unittest.main()
