from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("ODOO_URL", "https://example.invalid")
os.environ.setdefault("ODOO_DB", "test_db")
os.environ.setdefault("ODOO_USER", "test_user")
os.environ.setdefault("ODOO_API_KEY", "test_key")

import fetch


class ExpenseStructureTest(unittest.TestCase):
    @patch.object(fetch, "execute")
    def test_groups_direct_and_operating_expenses(self, execute_mock) -> None:
        execute_mock.side_effect = [
            [
                {"account_id": [10, "5000 - مواد خام"], "debit": 1000.0, "credit": 50.0},
                {"account_id": [20, "6100 - إيجار"], "debit": 400.0, "credit": 0.0},
                {"account_id": [30, "6200 - تسوية"], "debit": 100.0, "credit": 100.0},
            ],
            [
                {"id": 10, "code": "5000", "name": "مواد خام", "account_type": "expense_direct_cost"},
                {"id": 20, "code": "6100", "name": "إيجار", "account_type": "expense"},
                {"id": 30, "code": "6200", "name": "تسوية", "account_type": "expense"},
            ],
        ]

        result = fetch.get_expense_structure(7, "2026-01-01", "2026-07-20")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["direct_cost"], 950.0)
        self.assertEqual(result["operating_expense"], 400.0)
        self.assertEqual(result["total_expenses"], 1350.0)
        self.assertEqual(len(result["accounts"]), 2)
        self.assertEqual(result["accounts"][0]["classification"], "direct_cost")
        self.assertEqual(result["accounts"][1]["classification"], "operating_expense")

    @patch.object(fetch, "execute", side_effect=RuntimeError("connection failure"))
    def test_hides_raw_accounting_error(self, _execute_mock) -> None:
        result = fetch.get_expense_structure(7, "2026-01-01", "2026-07-20")
        self.assertEqual(result, {"status": "unavailable", "reason": "accounting_read_failed"})


if __name__ == "__main__":
    unittest.main()
