#!/usr/bin/env python3
"""Check that WIF import resolves to the expected Catecash address."""

import hashlib
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "pool-wallet-helper/target/release/catecash-pool-wallet-helper"
ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def encode_wif(prefix):
    payload = bytes([prefix]) + (1).to_bytes(32, "big") + b"\x01"
    checked = payload + hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    number = int.from_bytes(checked, "big")
    result = ""
    while number:
        number, remainder = divmod(number, 58)
        result = ALPHABET[remainder] + result
    return result


class PoolWalletHelperTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not HELPER.is_file():
            subprocess.run(["cargo", "build", "--manifest-path", str(ROOT / "pool-wallet-helper/Cargo.toml"),
                            "--release", "--offline"], cwd=ROOT, check=True)

    def run_helper(self, wif, network):
        return subprocess.run([str(HELPER), network], input=wif, text=True, capture_output=True, timeout=5)

    def test_mainnet_wif_matches_independent_address_vector(self):
        result = self.run_helper(encode_wif(0xd2), "catecash-mainnet")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "CaMSNvH5AeynDGHkV3ZgvfzRDwXBxs4u8dN")

    def test_wrong_network_and_checksum_are_rejected(self):
        wif = encode_wif(0xd2)
        self.assertNotEqual(self.run_helper(wif, "catecash-testnet").returncode, 0)
        bad = wif[:-1] + ("1" if wif[-1] != "1" else "2")
        self.assertNotEqual(self.run_helper(bad, "catecash-mainnet").returncode, 0)


if __name__ == "__main__":
    unittest.main()
