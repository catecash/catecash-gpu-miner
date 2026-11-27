#!/usr/bin/env python3
"""Check separate reward plans, exact rounding, maturity, and reorg effects."""

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pool_accounting import PoolLedger, coinbase_reward_atoms
from smoke_solo import COINBASE


class PoolAccountingTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "ledger.sqlite3"
        self.ledger = PoolLedger(self.path)

    def share(self, plan, address, number):
        nonce = number.to_bytes(32, "little")
        return self.ledger.add_share(plan, address, "mac", "job", nonce, b"solution", 10)

    def test_proportional_rounds_and_matures_exactly(self):
        self.share("proportional", "A", 1)
        self.share("proportional", "A", 2)
        self.share("proportional", "B", 3)
        self.share("pplns", "C", 4)
        self.assertEqual(self.ledger.record_block("a" * 64, "proportional", 10, 100), {"A": 67, "B": 33})
        self.assertEqual(self.ledger.balance_atoms("A"), 0)
        self.assertEqual(self.ledger.reconcile_block("a" * 64, "a" * 64, 119), "pending")
        self.assertEqual(self.ledger.reconcile_block("a" * 64, "a" * 64, 120), "mature")
        self.assertEqual(self.ledger.balance_atoms("A"), 67)
        self.assertEqual(self.ledger.reconcile_block("a" * 64, "b" * 64, 0), "orphaned")
        self.assertEqual(self.ledger.balance_atoms("A"), 0)

    def test_plans_have_separate_rounds(self):
        self.share("proportional", "A", 1)
        self.share("pplns", "B", 2)
        self.share("pplns", "C", 3)
        self.assertEqual(self.ledger.record_block("a" * 64, "proportional", 10, 10), {"A": 10})
        self.assertEqual(self.ledger.record_block("b" * 64, "pplns", 10, 11), {"B": 6, "C": 5})
        self.share("proportional", "D", 4)
        self.assertEqual(self.ledger.record_block("c" * 64, "proportional", 11, 10), {"D": 10})

    def test_orphaned_proportional_round_rolls_into_next_block(self):
        self.share("proportional", "A", 1)
        self.ledger.record_block("a" * 64, "proportional", 10, 10)
        self.ledger.reconcile_block("a" * 64, "b" * 64, 0)
        self.share("proportional", "B", 2)
        self.assertEqual(self.ledger.record_block("c" * 64, "proportional", 11, 10), {"A": 5, "B": 5})

    def test_duplicate_share_stays_duplicate_after_reopen(self):
        self.assertIsNotNone(self.share("proportional", "A", 1))
        self.assertIsNone(self.share("proportional", "A", 1))
        reopened = PoolLedger(self.path)
        self.assertIsNone(reopened.add_share("proportional", "A", "mac", "job", (1).to_bytes(32, "little"), b"solution", 10))

    def test_coinbase_reward_reads_first_output(self):
        self.assertEqual(coinbase_reward_atoms(COINBASE), 500000000000)


if __name__ == "__main__":
    unittest.main()
