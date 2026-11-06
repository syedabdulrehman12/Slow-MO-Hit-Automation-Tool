"""Minimal local web page with one button to start the SlowmoQA agent."""
from __future__ import annotations

import argparse
from collections import deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import threading
from urllib.parse import parse_qs, urlsplit
import webbrowser


ROOT = Path(__file__).resolve().parent
VENV_PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
LOG_LIMIT = 5000

PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SlowmoQA</title>
  <style>
    :root { color-scheme: dark; font-family: Segoe UI, sans-serif; background: #10131a; color: #e8edf5; }
    * { box-sizing: border-box; }
    body { display: grid; place-items: center; min-height: 100vh; margin: 0; padding: 20px; }
    main { width: min(100%, 900px); padding: 32px; border: 1px solid #2a3241; border-radius: 12px; background: #191e29; }
    header { text-align: center; }
    h1 { margin: 0 0 24px; font-size: 24px; }
    .controls { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
    button { width: 100%; padding: 15px 20px; border: 0; border-radius: 7px; background: #38b779; color: #08170f; font: inherit; font-size: 17px; font-weight: 700; cursor: pointer; }
    #stop { background: #ed6a66; color: #210a09; }
    button:disabled { opacity: .6; cursor: default; }
    #status { min-height: 24px; margin: 18px 0 0; color: #b7c3d5; font-size: 14px; line-height: 1.5; }
    h2 { margin: 28px 0 10px; font-size: 16px; }
    #logs { min-height: 220px; max-height: 55vh; margin: 0; padding: 14px; overflow: auto; border: 1px solid #2a3241; border-radius: 7px; background: #0c0f15; color: #d3dae6; white-space: pre-wrap; overflow-wrap: anywhere; font: 12px/1.5 Consolas, monospace; }
  </style>
</head>
<body>
  <main>
    <h1>SlowmoQA</h1>
    <div class="controls">
      <button id="start">Start test</button>
      <button id="stop" disabled>Stop test</button>
    </div>
    <p id="status" role="status">Ready</p>
    <h2>Test logs</h2>
    <pre id="logs" aria-live="polite"></pre>
  </main>
  <script>
    const button = document.getElementById("start");
    const stopButton = document.getElementById("stop");
    const status = document.getElementById("status");
    const logs = document.getElementById("logs");
    let lastLogId = 0;
    let logLines = [];
    button.addEventListener("click", async () => {
      button.disabled = true;
      status.textContent = "Starting test...";
      try {
        const response = await fetch("/api/start", { method: "POST" });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Could not start test");
        status.textContent = "Test is running...";
        refreshStatus();
      } catch (error) {
        status.textContent = error.message;
        button.disabled = false;
      }
    });
    stopButton.addEventListener("click", async () => {
      stopButton.disabled = true;
      status.textContent = "Stopping test...";
      try {
        const response = await fetch("/api/stop", { method: "POST" });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Could not stop test");
        status.textContent = data.stopping ? "Stopping test..." : "No test is running.";
        refreshStatus();
      } catch (error) {
        status.textContent = error.message;
        stopButton.disabled = false;
      }
    });
    async function refreshStatus() {
      try {
        const response = await fetch(`/api/state?after=${lastLogId}`, { cache: "no-store" });
        const data = await response.json();
        status.textContent = data.status;
        button.disabled = data.test_running;
        stopButton.disabled = !data.test_running || data.stopping;
        for (const entry of data.logs) {
          logLines.push(entry.text);
          lastLogId = entry.id;
        }
        if (logLines.length) {
          logs.textContent = logLines.join("");
          logs.scrollTop = logs.scrollHeight;
        }
      } catch (_) {
        status.textContent = "Dashboard connection lost";
      }
    }
    setInterval(refreshStatus, 1500);
    refreshStatus();
  </script>
</body>
</html>
"""


class DashboardService:
    def __init__(self) -> None:
        self._agent_lock = threading.Lock()
        self._agent: subprocess.Popen[str] | None = None
        self._last_exit_code: int | None = None
        self._stop_requested = False
        self._logs: deque[tuple[int, str]] = deque(maxlen=LOG_LIMIT)
        self._next_log_id = 1
        self._logs_lock = threading.Lock()

    def start_agent(self) -> None:
        with self._agent_lock:
            if self._agent is not None and self._agent.poll() is None:
                raise RuntimeError("The test is already running")
            if not VENV_PYTHON.is_file():
                raise RuntimeError(f"Virtual environment Python not found: {VENV_PYTHON}")
            self.append_log(
                f"[{datetime.now().astimezone().isoformat(timespec='seconds')}] "
                "Starting monkey suite with .venv Python\n")
            try:
                process = subprocess.Popen(
                    [
                        str(VENV_PYTHON),
                        "-u",
                        "-c",
                        "from slowmo_qa.runner import run_suite; "
                        "raise SystemExit(run_suite('monkey'))",
                    ],
                    cwd=ROOT,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                )
            except OSError as exc:
                self.append_log(f"Unable to start monkey suite: {exc}\n")
                raise RuntimeError(f"Unable to start test: {exc}") from exc
            self._last_exit_code = None
            self._stop_requested = False
            self._agent = process
        threading.Thread(
            target=self._read_agent_output,
            args=(process,),
            name="slowmoqa-agent-output",
            daemon=True,
        ).start()

    def append_log(self, text: str) -> None:
        with self._logs_lock:
            self._logs.append((self._next_log_id, text))
            self._next_log_id += 1

    def _read_agent_output(self, process: subprocess.Popen[str]) -> None:
        if process.stdout is not None:
            for line in process.stdout:
                self.append_log(line)
        exit_code = process.wait()
        with self._agent_lock:
            if self._agent is process:
                self._last_exit_code = exit_code
                self._agent = None
                stopped = self._stop_requested
                self._stop_requested = False
            else:
                stopped = False
        self.append_log(
            "Monkey suite stopped by user\n" if stopped
            else f"Monkey suite exited with code {exit_code}\n")

    def stop_agent(self) -> bool:
        with self._agent_lock:
            process = self._agent
            if process is None or process.poll() is not None:
                return False
            self._stop_requested = True
            process.terminate()
        self.append_log("Stop requested by user\n")
        return True

    def state(self, after_log_id: int = 0) -> dict[str, object]:
        with self._agent_lock:
            test_running = self._agent is not None and self._agent.poll() is None
            exit_code = self._last_exit_code
            stopping = test_running and self._stop_requested
        with self._logs_lock:
            logs = [
                {"id": entry_id, "text": text}
                for entry_id, text in self._logs
                if entry_id > after_log_id
            ]
        if test_running:
            status = "Stopping test..." if stopping else "Test is running..."
        elif exit_code is None:
            status = "Ready"
        elif exit_code == 0:
            status = "Test completed successfully."
        else:
            status = (
                f"Test failed (exit code {exit_code}). "
                "Check the latest run.log under artifacts."
            )
        return {
            "test_running": test_running,
            "stopping": stopping,
            "status": status,
            "logs": logs,
        }

    def close(self) -> None:
        with self._agent_lock:
            process = self._agent
            if process is not None and process.poll() is None:
                process.terminate()
        if process is not None and process.poll() is None:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def make_handler(service: DashboardService) -> type[BaseHTTPRequestHandler]:
    class DashboardHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/":
                content = PAGE.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(content)
            elif urlsplit(self.path).path == "/api/state":
                try:
                    query = parse_qs(urlsplit(self.path).query)
                    after = int(query.get("after", ["0"])[0])
                except ValueError:
                    self._json(400, {"error": "Invalid log cursor"})
                    return
                self._json(200, service.state(after))
            else:
                self.send_error(404)

        def do_POST(self) -> None:
            if self.path != "/api/start":
                if self.path == "/api/stop":
                    self._json(200, {
                        "ok": True,
                        "stopping": service.stop_agent(),
                    })
                    return
                self.send_error(404)
                return
            try:
                service.start_agent()
            except RuntimeError as exc:
                self._json(409, {"error": str(exc)})
                return
            self._json(200, {"ok": True})

        def _json(self, status_code: int, payload: dict[str, object]) -> None:
            content = json.dumps(payload).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    return DashboardHandler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765, help="Local web server port")
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")

    service = DashboardService()
    server = ThreadingHTTPServer(
        ("127.0.0.1", args.port), make_handler(service))
    server.daemon_threads = True
    url = f"http://127.0.0.1:{args.port}/"
    print(f"SlowmoQA test button: {url}")
    print("Press Ctrl+C to stop.")
    try:
        webbrowser.open(url)
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping SlowmoQA dashboard.")
    finally:
        server.server_close()
        service.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
