#!/usr/bin/env python3
"""Check that the development coordinator cannot silently open paid mining."""

import copy
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pool_server import Pool
from smoke_solo import ADDRESS, template

NODE_PAYOUT = "yPoqh62pqtcTrm3jLimZn46zTRJGyqmBsg1"


class PoolGateTest(unittest.TestCase):
    def make_pool(self, development=False):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        pool = Pool("http://127.0.0.1:34342", None, "catecash-devnet", NODE_PAYOUT,
                    Path(directory.name) / "ledger.sqlite3", Path("/bin/true"), development)
        node_template = template()
        node_template["target"] = "0e" + "ff" * 31
        def fake_rpc(method, params):
            if method == "getblockchaininfo":
                return {"chain": "catecash-devnet", "blocks": 7726, "headers": 7726}
            if method == "getblocktemplate":
                return copy.deepcopy(node_template)
            raise AssertionError(method)
        pool._rpc = fake_rpc
        return pool

    def test_closed_pool_rejects_jobs_and_shares(self):
        pool = self.make_pool()
        self.assertFalse(pool.status()["ready"])
        self.assertFalse(pool.status()["payouts_enabled"])
        with self.assertRaisesRegex(RuntimeError, "closed"):
            pool.job(ADDRESS, "mac", "proportional")
        with self.assertRaisesRegex(RuntimeError, "closed"):
            pool.share({})

    def test_development_job_is_bound_to_worker_and_prefix(self):
        pool = self.make_pool(development=True)
        job = pool.job(ADDRESS, "mac", "proportional")
        self.assertEqual(job["network"], "catecash-devnet")
        self.assertEqual(job["plan"], "proportional")
        self.assertEqual(len(bytes.fromhex(job["header"])), 108)
        self.assertEqual(len(bytes.fromhex(job["nonce_prefix"])), 4)
        self.assertEqual(job["job_id"], pool.job(ADDRESS, "mac", "proportional")["job_id"])
        pool.template_at = 0
        self.assertEqual(job["job_id"], pool.job(ADDRESS, "mac", "proportional")["job_id"])
        self.assertNotEqual(job["job_id"], pool.job(ADDRESS, "mac", "pplns")["job_id"])
        self.assertNotEqual(job["job_id"], pool.job(ADDRESS, "other", "proportional")["job_id"])
        self.assertEqual(pool.share({"job_id": job["job_id"], "address": ADDRESS,
                                      "worker": "other", "plan": "proportional"})["reason"], "job identity mismatch")


if __name__ == "__main__":
    unittest.main()
