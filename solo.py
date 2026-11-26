#!/usr/bin/env python3
"""Mine Catecash blocks on the local Apple GPU using a Zebra block template."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import sys
import time
from urllib.parse import urlparse

from preflight import NETWORKS, rpc
from template_work import prepare_template


SOLUTION_LINE = re.compile(r"^sol: (\S+) ([0-9a-fA-F]{8}) ([0-9a-fA-F]{64}) (fd4005[0-9a-fA-F]{2688})$")


def compact_size(value: int) -> bytes:
    if value < 0:
        raise ValueError("negative transaction count")
    if value < 253:
        return bytes([value])
    if value <= 0xFFFF:
        return b"\xfd" + value.to_bytes(2, "little")
    if value <= 0xFFFFFFFF:
        return b"\xfe" + value.to_bytes(4, "little")
    return b"\xff" + value.to_bytes(8, "little")


def header_prefix(template: dict) -> bytes:
    roots = template["defaultroots"]
    version = int(template["version"]).to_bytes(4, "little")
    prev = bytes.fromhex(template["previousblockhash"])[::-1]
    merkle = bytes.fromhex(roots["merkleroot"])[::-1]
    commitment = bytes.fromhex(template["blockcommitmentshash"])[::-1]
    timestamp = int(template["curtime"]).to_bytes(4, "little")
    bits = bytes.fromhex(template["bits"])[::-1]
    header = version + prev + merkle + commitment + timestamp + bits
    if len(header) != 108:
        raise ValueError("invalid block template header fields")
    if not int(template["mintime"]) <= int(template["curtime"]) <= int(template["maxtime"]):
        raise ValueError("template time outside allowed range")
    return header


def mining_job(template: dict, job_id: str) -> bytes:
    target = bytes.fromhex(template["target"])[::-1]
    if len(target) != 32:
        raise ValueError("invalid target length")
    return f"{target.hex()} {job_id} {header_prefix(template).hex()} \n".encode("ascii")


def solved_block(template: dict, nonce: bytes, encoded_solution: bytes) -> bytes:
    if len(nonce) != 32 or len(encoded_solution) != 1347 or encoded_solution[:3] != b"\xfd\x40\x05":
        raise ValueError("invalid solver output")
    transactions = [bytes.fromhex(template["coinbasetxn"]["data"])]
    transactions.extend(bytes.fromhex(tx["data"]) for tx in template["transactions"])
    return (header_prefix(template) + nonce + encoded_solution +
            compact_size(len(transactions)) + b"".join(transactions))


def double_sha256(data: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def run(args: argparse.Namespace) -> int:
    info = rpc(args.rpc_url, args.cookie_file, "getblockchaininfo", [])
    network = str(info.get("chain", "")).lower()
    if network != args.network:
        raise ValueError(f"node is on {network!r}, expected {args.network!r}")

    binary = Path(__file__).resolve().parent / "sa-solver"
    if not binary.is_file():
        raise FileNotFoundError("sa-solver is missing; run make first")
    proc = subprocess.Popen([str(binary), "--mining", "--use", str(args.device)],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, bufsize=0)
    try:
        banner = proc.stdout.readline().decode("ascii", errors="replace").strip()
        if banner != "SILENTARMY mining mode ready":
            raise RuntimeError(f"GPU solver did not start: {banner}")
        selector = selectors.DefaultSelector()
        selector.register(proc.stdout, selectors.EVENT_READ)
        current = None
        job_id = 0
        next_poll = 0.0
        accepted = 0
        paused = False
        print(f"Mining {network} on GPU device {args.device}", flush=True)
        while True:
            if proc.poll() is not None:
                raise RuntimeError(f"GPU solver exited with status {proc.returncode}")
            if args.intensity < 100:
                active = (time.monotonic() % 1.0) < (args.intensity / 100.0)
                if active and paused:
                    os.kill(proc.pid, signal.SIGCONT)
                    paused = False
                elif not active and not paused:
                    os.kill(proc.pid, signal.SIGSTOP)
                    paused = True
            if time.monotonic() >= next_poll:
                template = rpc(args.rpc_url, args.cookie_file, "getblocktemplate", [])
                if args.payout_address:
                    template = prepare_template(template, args.payout_address, network)
                fingerprint = (template["height"], template["previousblockhash"],
                               template["curtime"], template["bits"],
                               template["defaultroots"]["merkleroot"],
                               template["blockcommitmentshash"])
                if current is None or fingerprint != current[0]:
                    job_id += 1
                    proc.stdin.write(mining_job(template, str(job_id)))
                    proc.stdin.flush()
                    current = (fingerprint, template, str(job_id))
                    print(f"Working on height {template['height']} (job {job_id})", flush=True)
                next_poll = time.monotonic() + args.poll_seconds
            ready = selector.select(timeout=min(0.1, max(0.0, next_poll - time.monotonic())))
            if not ready:
                continue
            line = proc.stdout.readline().decode("ascii", errors="replace").strip()
            if not line:
                continue
            match = SOLUTION_LINE.fullmatch(line)
            if not match:
                if args.verbose and not line.startswith("status:"):
                    print(f"solver: {line}")
                continue
            found_id, found_time, nonce_hex, solution_hex = match.groups()
            if current is None or found_id != current[2]:
                continue
            template = current[1]
            if found_time.lower() != int(template["curtime"]).to_bytes(4, "little").hex():
                continue
            nonce = bytes.fromhex(nonce_hex)
            encoded_solution = bytes.fromhex(solution_hex)
            block = solved_block(template, nonce, encoded_solution)
            block_hash = double_sha256(block[:140 + 1347])
            target = bytes.fromhex(template["target"])[::-1]
            if int.from_bytes(block_hash, "little") > int.from_bytes(target, "little"):
                raise RuntimeError("GPU solver emitted a hash above target")
            proposal = rpc(args.rpc_url, args.cookie_file, "getblocktemplate",
                           [{"mode": "proposal", "data": block.hex()}])
            if proposal is not None:
                print(f"Node rejected block proposal: {proposal}", file=sys.stderr)
                next_poll = 0.0
                continue
            result = rpc(args.rpc_url, args.cookie_file, "submitblock", [block.hex()])
            if result is None:
                accepted += 1
                print(f"Accepted block at height {template['height']}: {block_hash[::-1].hex()}", flush=True)
                if args.max_blocks and accepted >= args.max_blocks:
                    return 0
            else:
                print(f"Node rejected block: {result}", file=sys.stderr)
            next_poll = 0.0
    finally:
        if 'paused' in locals() and paused and proc.poll() is None:
            os.kill(proc.pid, signal.SIGCONT)
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rpc-url", required=True)
    parser.add_argument("--cookie-file", type=Path)
    parser.add_argument("--network", required=True, choices=sorted(NETWORKS))
    parser.add_argument("--payout-address", help="transparent Catecash P2PKH mining address")
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--intensity", type=int, default=100, help="approximate GPU duty cycle, 10 to 100 percent")
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--max-blocks", type=int, default=0, help="stop after N accepted blocks (0 means continuous)")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    url = urlparse(args.rpc_url)
    if (url.scheme == "http" and url.hostname not in {"127.0.0.1", "localhost", "::1"}) or url.scheme not in {"http", "https"} or url.hostname is None:
        parser.error("RPC must use loopback HTTP or HTTPS")
    if args.poll_seconds <= 0 or args.max_blocks < 0 or args.device < 0 or not 10 <= args.intensity <= 100:
        parser.error("device and max-blocks must be nonnegative; poll-seconds positive; intensity 10 to 100")
    try:
        return run(args)
    except KeyboardInterrupt:
        print("Stopped", file=sys.stderr)
        return 130
    except (OSError, ValueError, KeyError, RuntimeError, json.JSONDecodeError) as error:
        print(f"miner failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
