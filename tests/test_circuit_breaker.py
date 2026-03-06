from __future__ import annotations

from pathlib import Path
import unittest

from src.agent.core.circuit_breaker import ProviderCircuitBreaker


class ProviderCircuitBreakerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.sqlite_path = Path(f"tests/.tmp_provider_health_{self._testMethodName}.sqlite")
        if self.sqlite_path.exists():
            self.sqlite_path.unlink()

    def tearDown(self) -> None:
        try:
            if self.sqlite_path.exists():
                self.sqlite_path.unlink()
        except PermissionError:
            pass

    def test_opens_after_threshold_and_half_opens_after_ttl(self) -> None:
        breaker = ProviderCircuitBreaker(
            sqlite_path=self.sqlite_path,
            failure_threshold=2,
            open_ttl_sec=10.0,
            half_open_probe_after_sec=5.0,
            cfg={},
        )

        self.assertTrue(breaker.allow("openalex", now=100.0))
        breaker.record_failure("openalex", "boom-1", now=100.0)
        self.assertTrue(breaker.allow("openalex", now=101.0))
        breaker.record_failure("openalex", "boom-2", now=101.0)

        health = breaker.get_state("openalex")
        self.assertEqual(health.state, "open")
        self.assertEqual(health.consecutive_failures, 2)
        self.assertFalse(breaker.allow("openalex", now=105.0))
        self.assertTrue(breaker.allow("openalex", now=111.0))
        self.assertEqual(breaker.get_state("openalex").state, "half_open")

    def test_success_closes_breaker_and_resets_failures(self) -> None:
        breaker = ProviderCircuitBreaker(
            sqlite_path=self.sqlite_path,
            failure_threshold=1,
            open_ttl_sec=10.0,
            half_open_probe_after_sec=1.0,
            cfg={},
        )

        breaker.record_failure("semantic_scholar", "boom", now=10.0)
        self.assertEqual(breaker.get_state("semantic_scholar").state, "open")
        self.assertTrue(breaker.allow("semantic_scholar", now=21.0))
        breaker.record_success("semantic_scholar")

        health = breaker.get_state("semantic_scholar")
        self.assertEqual(health.state, "closed")
        self.assertEqual(health.consecutive_failures, 0)
        self.assertEqual(health.last_error, "")


if __name__ == "__main__":
    unittest.main()
