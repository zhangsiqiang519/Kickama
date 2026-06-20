import http.server
import socket
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import health_check  # noqa: E402


class HealthHandler(http.server.BaseHTTPRequestHandler):
    status_code = 200

    def do_GET(self) -> None:
        self.send_response(self.status_code)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, format: str, *args: object) -> None:
        return


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class PrometheusHealthCheckTest(unittest.TestCase):
    def run_mock_service(self, status_code: int) -> int:
        port = free_port()
        handler = type("MockHealthHandler", (HealthHandler,), {"status_code": status_code})
        server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        return port

    def results_for_status(self, status_code: int) -> dict:
        port = self.run_mock_service(status_code)
        services = {
            "mock-service": {
                "host": "127.0.0.1",
                "port": port,
                "path": "/health",
                "timeout": 2,
            }
        }
        with patch.dict(health_check.SERVICES, services, clear=True):
            return health_check.run_health_checks(service="mock-service")

    def test_prometheus_output_includes_healthy_service_metrics(self) -> None:
        results = self.results_for_status(200)
        output = health_check.format_prometheus_report(results)

        self.assertIn('kickama_health_service_up{service="mock-service"', output)
        self.assertIn("} 1", output)
        self.assertIn("kickama_health_service_latency_ms", output)
        self.assertIn("kickama_health_service_http_status_code", output)
        self.assertIn(" 200", output)
        self.assertIn("kickama_health_check_timestamp_seconds", output)

    def test_prometheus_output_marks_unhealthy_service_down(self) -> None:
        results = self.results_for_status(503)
        output = health_check.format_prometheus_report(results)

        self.assertEqual(results["overall_status"], "DEGRADED")
        self.assertIn('kickama_health_service_up{service="mock-service"', output)
        self.assertIn("} 0", output)
        self.assertIn(" 503", output)


if __name__ == "__main__":
    unittest.main()
