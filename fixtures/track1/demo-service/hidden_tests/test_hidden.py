import unittest

from retry_guard import execute_with_retry


class HiddenRetryGuardTests(unittest.TestCase):
    def test_ambiguous_timeout_does_not_repeat_idempotent_side_effect(self):
        calls = []

        def operation(remaining, key):
            calls.append((remaining, key))
            raise TimeoutError("the server may have committed the effect")

        with self.assertRaises(TimeoutError):
            execute_with_retry(operation, 0.25, idempotency_key="order-42")

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], "order-42")
