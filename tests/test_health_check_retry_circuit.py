import sys
import unittest
from pathlib import Path
from typing import List


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import health_check  # noqa: E402


class HealthCheckRetryCircuitTest(unittest.TestCase):
    def test_http_probe_retries_until_success(self) -> None:
        attempts = 0

        def request_once(host: str, port: int, path: str, timeout: int) -> tuple[int, str]:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise ConnectionRefusedError("not ready")
            return 200, "ok"

        status, detail, code = health_check.check_http_service(
            "localhost",
            8080,
            "/health",
            5,
            max_retries=2,
            backoff_factor=0,
            request_once=request_once,
            sleep=lambda seconds: None,
        )

        self.assertEqual(status, "OK")
        self.assertEqual(code, 200)
        self.assertEqual(attempts, 2)
        self.assertIn("after 2 attempts", detail)

    def test_retry_backoff_uses_exponential_schedule(self) -> None:
        sleeps: List[float] = []

        def request_once(host: str, port: int, path: str, timeout: int) -> tuple[int, str]:
            raise TimeoutError("timeout")

        status, detail, code = health_check.check_http_service(
            "localhost",
            8080,
            "/health",
            5,
            max_retries=2,
            backoff_factor=2,
            backoff_base_delay=0.5,
            request_once=request_once,
            sleep=sleeps.append,
        )

        self.assertEqual(status, "CRITICAL")
        self.assertEqual(code, 0)
        self.assertIn("timeout", detail)
        self.assertEqual(sleeps, [0.5, 1.0])

    def test_circuit_breaker_opens_after_threshold(self) -> None:
        breaker = health_check.CircuitBreaker(threshold=2, cooldown_seconds=30, clock=lambda: 100.0)

        breaker.record_failure()
        self.assertTrue(breaker.allow_request())

        breaker.record_failure()
        self.assertFalse(breaker.allow_request())

    def test_circuit_breaker_resets_after_cooldown(self) -> None:
        now = 100.0

        def clock() -> float:
            return now

        breaker = health_check.CircuitBreaker(threshold=1, cooldown_seconds=30, clock=clock)
        breaker.record_failure()
        self.assertFalse(breaker.allow_request())

        now = 131.0
        self.assertTrue(breaker.allow_request())

    def test_health_summary_counts_statuses_and_circuit_breakers(self) -> None:
        results = {
            "services": {
                "backend": {"status": "OK"},
                "market": {"status": "WARNING", "circuit": "closed"},
                "frailbox": {"status": "CRITICAL", "circuit": "open"},
            },
            "infrastructure": {"redis": {"status": "CRITICAL"}},
            "system": {"disk": {"status": "OK"}, "memory": {"status": "WARNING"}},
        }

        self.assertEqual(
            health_check.summarize_results(results),
            {
                "ok": 2,
                "warning": 2,
                "critical": 2,
                "circuit_open": 1,
            },
        )

    def test_retry_flags_are_parsed(self) -> None:
        args = health_check.parse_args(
            [
                "--max-retries",
                "3",
                "--backoff-factor",
                "1.5",
                "--circuit-threshold",
                "4",
            ]
        )

        self.assertEqual(args.max_retries, 3)
        self.assertEqual(args.backoff_factor, 1.5)
        self.assertEqual(args.circuit_threshold, 4)


if __name__ == "__main__":
    unittest.main()
