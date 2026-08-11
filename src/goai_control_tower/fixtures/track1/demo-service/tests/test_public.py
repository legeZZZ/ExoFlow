import unittest

from retry_guard import execute_with_retry


class PublicRetryGuardTests(unittest.TestCase):
    def test_retry_uses_one_total_timeout_budget(self):
        budgets = []

        def operation(remaining, _key):
            budgets.append(remaining)
            if len(budgets) == 1:
                raise TimeoutError("transient timeout")
            return "ok"

        self.assertEqual(execute_with_retry(operation, 0.25), "ok")
        self.assertEqual(len(budgets), 2)
        self.assertLess(budgets[1], budgets[0])

    def test_invalid_budget_is_rejected(self):
        with self.assertRaises(ValueError):
            execute_with_retry(lambda _remaining, _key: "ok", 0, attempts=1)
