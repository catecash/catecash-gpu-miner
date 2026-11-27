#!/usr/bin/env python3
"""Prototype Catecash pool worker using the bundled Apple GPU solver."""

import argparse
import json
from pathlib import Path
import re
import selectors
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from preflight import NETWORKS
from solo import double_sha256
from template_work import payout_script


SOLUTION = re.compile(r"^sol: ([0-9a-f]{1,32}) ([0-9a-f]{8}) ([0-9a-f]{56}) (fd4005[0-9a-f]{2688})$")
WORKER = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


def pool_request(base, path, payload=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(base + path, data=data, headers={"Content-Type": "application/json"} if data else {})
    try:
        with urlopen(request, timeout=10) as response:
            if response.status != 200:
                raise RuntimeError(f"pool returned HTTP {response.status}")
            result = json.load(response)
    except HTTPError as error:
        detail = error.read(512).decode("utf-8", errors="replace")
        raise RuntimeError(f"pool returned HTTP {error.code}: {detail}") from error
    if not isinstance(result, dict):
        raise ValueError("pool response must be a JSON object")
    return result


def validate_job(job, network, plan):
    if job.get("network") != network:
        raise ValueError("pool job is for a different network")
    if job.get("plan") != plan:
        raise ValueError("pool job is for a different reward plan")
    job_id = job.get("job_id")
    if not isinstance(job_id, str) or not re.fullmatch(r"[0-9a-f]{1,32}", job_id):
        raise ValueError("pool job ID is invalid")
    header = bytes.fromhex(job["header"])
    prefix = bytes.fromhex(job["nonce_prefix"])
    target = bytes.fromhex(job["share_target"])
    if len(header) != 108 or len(prefix) != 4 or len(target) != 32:
        raise ValueError("pool job has invalid header, nonce prefix, or target length")
    if not isinstance(job.get("height"), int) or job["height"] < 1:
        raise ValueError("pool job height is invalid")
    # The solver requires the final 12 nonce bytes to be zero.
    return header, prefix, target


def check(args):
    status = pool_request(args.pool_url, "/v1/status")
    if status.get("protocol") != "catecash-pool/1" or status.get("network") != args.network:
        raise ValueError("pool protocol or network does not match")
    local_development = (args.allow_unpaid_development and args.network != "catecash-mainnet"
                         and urlparse(args.pool_url).hostname in {"localhost", "127.0.0.1", "::1"})
    if status.get("payouts_enabled") is False and not local_development:
        raise RuntimeError("pool has not enabled miner payouts")
    if status.get("ready") is not True:
        raise RuntimeError("pool is not ready to issue work")
    query = urlencode({"address": args.payout_address, "worker": args.worker, "plan": args.plan})
    job = pool_request(args.pool_url, "/v1/job?" + query)
    validate_job(job, args.network, args.plan)
    print(f"Pool ready: {args.network}, {args.plan}, height {job['height']}, worker {args.worker}", flush=True)
    return job


def run(args):
    job = check(args)
    if args.check:
        return 0
    binary = Path(__file__).resolve().parent / "sa-solver"
    if not binary.is_file():
        raise FileNotFoundError("sa-solver is missing; run make first")
    proc = subprocess.Popen([str(binary), "--mining", "--use", str(args.device),
                             "--duty-cycle", str(args.intensity)],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, bufsize=0)
    try:
        banner = proc.stdout.readline().decode("ascii", errors="replace").strip()
        if banner != "SILENTARMY mining mode ready":
            raise RuntimeError(f"GPU solver did not start: {banner}")
        selector = selectors.DefaultSelector()
        selector.register(proc.stdout, selectors.EVENT_READ)
        current_id = None
        next_poll = 0.0
        accepted = 0
        print(f"Mining with pool on GPU device {args.device} at {args.intensity}% duty cycle", flush=True)
        while True:
            if proc.poll() is not None:
                raise RuntimeError(f"GPU solver exited with status {proc.returncode}")
            if time.monotonic() >= next_poll:
                if current_id is not None:
                    query = urlencode({"address": args.payout_address, "worker": args.worker, "plan": args.plan})
                    job = pool_request(args.pool_url, "/v1/job?" + query)
                header, prefix, target = validate_job(job, args.network, args.plan)
                if job["job_id"] != current_id:
                    # The solver accepts a little-endian target and appends its own nonce suffix.
                    line = f"{target[::-1].hex()} {job['job_id']} {header.hex()} {prefix.hex()}\n"
                    proc.stdin.write(line.encode("ascii"))
                    proc.stdin.flush()
                    current_id = job["job_id"]
                    print(f"Working on height {job['height']} (job {current_id})", flush=True)
                next_poll = time.monotonic() + args.poll_seconds
            ready = selector.select(timeout=min(0.1, max(0.0, next_poll - time.monotonic())))
            if not ready:
                continue
            line = proc.stdout.readline().decode("ascii", errors="replace").strip()
            match = SOLUTION.fullmatch(line)
            if not match:
                if args.verbose and line and not line.startswith("status:"):
                    print(f"solver: {line}", flush=True)
                continue
            found_id, found_time, suffix_hex, solution_hex = match.groups()
            if found_id != current_id or found_time != header[100:104].hex():
                continue
            nonce = prefix + bytes.fromhex(suffix_hex)
            solution = bytes.fromhex(solution_hex)
            digest = double_sha256(header + nonce + solution)
            if int.from_bytes(digest, "little") > int.from_bytes(target[::-1], "little"):
                raise RuntimeError("GPU solver emitted a hash above share target")
            reply = pool_request(args.pool_url, "/v1/share", {
                "address": args.payout_address, "worker": args.worker,
                "plan": args.plan,
                "job_id": found_id, "nonce": nonce.hex(), "solution": solution_hex,
            })
            if reply.get("accepted") is True:
                accepted += 1
                print(f"Accepted share {accepted} at height {job['height']}", flush=True)
                if args.max_shares and accepted >= args.max_shares:
                    return 0
            else:
                print(f"Rejected share: {reply.get('reason', 'unknown reason')}", flush=True)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pool-url", required=True)
    parser.add_argument("--network", required=True, choices=sorted(NETWORKS))
    parser.add_argument("--payout-address", required=True)
    parser.add_argument("--worker", default="mac")
    parser.add_argument("--plan", choices=["proportional", "pplns"], default="proportional")
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--intensity", type=int, default=50)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--allow-unpaid-development", action="store_true",
                        help="allow a loopback devnet/testnet coordinator with no payouts")
    parser.add_argument("--max-shares", type=int, default=0, help="stop after N accepted shares (0 means continuous)")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    parsed = urlparse(args.pool_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        parser.error("pool URL must be an HTTP(S) origin without credentials or path")
    if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        parser.error("remote pools must use HTTPS")
    if not WORKER.fullmatch(args.worker):
        parser.error("worker must be 1–32 letters, numbers, underscores, or hyphens")
    if args.device < 0 or not 10 <= args.intensity <= 100 or args.poll_seconds <= 0 or args.max_shares < 0:
        parser.error("invalid device, intensity, poll interval, or max shares")
    args.pool_url = args.pool_url.rstrip("/")
    try:
        payout_script(args.payout_address, args.network)
        return run(args)
    except KeyboardInterrupt:
        print("Stopped", file=sys.stderr)
        return 130
    except (OSError, ValueError, KeyError, RuntimeError, HTTPError, URLError, json.JSONDecodeError) as error:
        print(f"pool worker failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
