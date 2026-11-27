#!/usr/bin/env python3
"""Development-only Catecash pool coordinator; no reward payouts are implemented."""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import threading
import time
from urllib.parse import parse_qs, urlparse

from preflight import NETWORKS, rpc
from pool_accounting import PoolLedger, coinbase_reward_atoms
from solo import double_sha256, header_prefix, solved_block
from template_work import payout_script, replace_payout


MAINNET_GENESIS = "050bf7476db81684aeb38337fc931bd8bc4480fde43fb0a14fef172f85c5c323"
WORKER = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
PLANS = {"proportional", "pplns"}
SHARE_TARGET = int("0fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff", 16)


class Pool:
    def __init__(self, rpc_url, cookie_file, network, operator_address, ledger_path, verifier, development=False):
        self.rpc_url, self.cookie_file, self.network = rpc_url, cookie_file, network
        self.operator_address = operator_address
        self.ledger_path, self.verifier = ledger_path, verifier
        self.development = development
        self.lock = threading.RLock()
        self.jobs = {}
        self.template = None
        self.template_at = 0.0
        self.reconciled_at = 0.0
        payout_script(operator_address, network)
        ledger_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.ledger = PoolLedger(ledger_path)

    def _rpc(self, method, params):
        return rpc(self.rpc_url, self.cookie_file, method, params)

    def check_node(self):
        info = self._rpc("getblockchaininfo", [])
        if info.get("chain") != self.network:
            raise ValueError("Zebra network does not match pool network")
        if self.network == "catecash-mainnet" and self._rpc("getblockhash", [0]) != MAINNET_GENESIS:
            raise ValueError("Zebra mainnet genesis does not match")
        if int(info.get("headers", info["blocks"])) - int(info["blocks"]) > 2:
            raise RuntimeError("Zebra is still synchronizing")
        return info

    def refresh(self):
        with self.lock:
            if self.template is not None and time.monotonic() - self.template_at < 2:
                return self.template
            self.check_node()
            candidate = self._rpc("getblocktemplate", [])
            original = candidate["coinbasetxn"]["data"]
            expected_script = payout_script(self.operator_address, self.network)
            if replace_payout(original, expected_script) != original:
                raise ValueError("node coinbase pays a different address than the configured operator payout")
            header_prefix(candidate)
            network_target = int(candidate["target"], 16)
            if not 0 < network_target <= SHARE_TARGET:
                raise ValueError("network target is outside the supported share range")
            old = self.template
            def fingerprint(item):
                return (item["height"], item["previousblockhash"], item["curtime"], item["bits"],
                        item["defaultroots"]["merkleroot"], item["blockcommitmentshash"])
            self.template_at = time.monotonic()
            if old is not None and fingerprint(old) == fingerprint(candidate):
                return old
            self.template = candidate
            if old is not None and (old["previousblockhash"], old["height"]) != (candidate["previousblockhash"], candidate["height"]):
                self.jobs.clear()
            return candidate

    def status(self):
        try:
            info = self.check_node()
            self.reconcile(int(info["blocks"]))
            return {"protocol": "catecash-pool/1", "network": self.network,
                    "ready": self.development, "height": info["blocks"],
                    "payouts_enabled": False, "plans": sorted(PLANS),
                    "warning": "Development service: no miner payouts"}
        except (OSError, ValueError, KeyError, RuntimeError):
            return {"protocol": "catecash-pool/1", "network": self.network,
                    "ready": False, "payouts_enabled": False, "plans": sorted(PLANS)}

    def reconcile(self, tip_height):
        with self.lock:
            if time.monotonic() - self.reconciled_at < 20:
                return
            for block_hash, height in self.ledger.blocks_to_reconcile():
                if height <= tip_height:
                    canonical = self._rpc("getblockhash", [height])
                    self.ledger.reconcile_block(block_hash, canonical, tip_height - height + 1)
                else:
                    self.ledger.reconcile_block(block_hash, block_hash, 0)
            self.reconciled_at = time.monotonic()

    def job(self, address, worker, plan):
        if not self.development:
            raise RuntimeError("pool is closed until payout accounting is enabled")
        payout_script(address, self.network)
        if not WORKER.fullmatch(worker):
            raise ValueError("invalid worker name")
        if plan not in PLANS:
            raise ValueError("invalid reward plan")
        template = self.refresh()
        with self.lock:
            now = time.monotonic()
            self.jobs = {key: value for key, value in self.jobs.items() if now - value["created"] < 60}
            for existing in self.jobs.values():
                if existing["address"] == address and existing["worker"] == worker and existing["plan"] == plan and existing["template"] is template:
                    return existing["public"]
            prefixes = {item["prefix"] for item in self.jobs.values()}
            prefix = secrets.token_bytes(4)
            while prefix in prefixes:
                prefix = secrets.token_bytes(4)
            job_id = secrets.token_hex(12)
            public = {"network": self.network, "plan": plan, "job_id": job_id,
                      "height": int(template["height"]), "header": header_prefix(template).hex(),
                      "nonce_prefix": prefix.hex(), "share_target": SHARE_TARGET.to_bytes(32, "big").hex()}
            self.jobs[job_id] = {"address": address, "worker": worker, "plan": plan, "prefix": prefix,
                                 "template": template, "public": public, "created": now}
            return public

    def share(self, payload):
        if not self.development:
            raise RuntimeError("pool is closed until payout accounting is enabled")
        if not isinstance(payload, dict):
            raise ValueError("share must be a JSON object")
        job_id = payload.get("job_id")
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None or time.monotonic() - job["created"] >= 60:
                return {"accepted": False, "reason": "stale job"}
            if payload.get("address") != job["address"] or payload.get("worker") != job["worker"] or payload.get("plan") != job["plan"]:
                return {"accepted": False, "reason": "job identity mismatch"}
            try:
                nonce = bytes.fromhex(payload["nonce"])
                solution = bytes.fromhex(payload["solution"])
            except (KeyError, TypeError, ValueError):
                return {"accepted": False, "reason": "invalid share encoding"}
            if len(nonce) != 32 or not nonce.startswith(job["prefix"]) or len(solution) != 1347 or solution[:3] != b"\xfd\x40\x05":
                return {"accepted": False, "reason": "invalid share length or nonce prefix"}
            template = job["template"]
            header = header_prefix(template)
            digest = double_sha256(header + nonce + solution)
            if int.from_bytes(digest[::-1], "big") > SHARE_TARGET:
                return {"accepted": False, "reason": "share hash above target"}
            verified = subprocess.run([str(self.verifier), header.hex(), nonce.hex(), solution[3:].hex()],
                                      capture_output=True, timeout=10)
            if verified.returncode != 0:
                return {"accepted": False, "reason": "invalid Equihash solution"}
            block_hash = digest[::-1].hex()
            share_id = self.ledger.add_share(job["plan"], job["address"], job["worker"],
                                             job_id, nonce, solution, template["height"])
            if share_id is None:
                return {"accepted": False, "reason": "duplicate share"}
            network_target = int(template["target"], 16)
            if int(block_hash, 16) <= network_target:
                block = solved_block(template, nonce, solution)
                proposal = self._rpc("getblocktemplate", [{"mode": "proposal", "data": block.hex()}])
                if proposal is None:
                    outcome = self._rpc("submitblock", [block.hex()])
                    if outcome is None:
                        self.ledger.record_block(block_hash, job["plan"], template["height"],
                                                 coinbase_reward_atoms(template["coinbasetxn"]["data"]))
                        self.reconciled_at = 0.0
                    self.template_at = 0.0
            return {"accepted": True, "payouts_enabled": False}


def handler_for(pool):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format_string, *args):
            print(format_string % args, flush=True)

        def send_json(self, status, payload):
            data = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            route = urlparse(self.path)
            if route.path == "/v1/status":
                return self.send_json(200, pool.status())
            if route.path != "/v1/job":
                return self.send_json(404, {"error": "not found"})
            query = parse_qs(route.query)
            try:
                address, worker, plan = query["address"][0], query["worker"][0], query["plan"][0]
                return self.send_json(200, pool.job(address, worker, plan))
            except (KeyError, IndexError, ValueError, RuntimeError, OSError) as error:
                return self.send_json(400, {"error": str(error)})

        def do_POST(self):
            if self.path != "/v1/share":
                return self.send_json(404, {"error": "not found"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 4096:
                    raise ValueError("invalid share length")
                return self.send_json(200, pool.share(json.loads(self.rfile.read(length))))
            except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired) as error:
                return self.send_json(400, {"error": str(error)})
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rpc-url", required=True)
    parser.add_argument("--cookie-file", type=Path, required=True)
    parser.add_argument("--network", required=True, choices=sorted(NETWORKS))
    parser.add_argument("--operator-address", required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--verifier", type=Path, required=True)
    parser.add_argument("--port", type=int, default=3085)
    parser.add_argument("--development", action="store_true", help="issue unpaid work on loopback for local testing only")
    args = parser.parse_args()
    if urlparse(args.rpc_url).hostname not in {"127.0.0.1", "localhost", "::1"}:
        parser.error("pool Zebra RPC must be on loopback")
    if args.development and args.network == "catecash-mainnet":
        parser.error("unpaid development mining is not allowed on mainnet")
    if not args.verifier.is_file() or not os.access(args.verifier, os.X_OK):
        parser.error("pool verifier binary is missing or not executable")
    pool = Pool(args.rpc_url, args.cookie_file, args.network, args.operator_address, args.ledger, args.verifier,
                development=args.development)
    pool.check_node()
    ThreadingHTTPServer(("127.0.0.1", args.port), handler_for(pool)).serve_forever()


if __name__ == "__main__":
    main()
