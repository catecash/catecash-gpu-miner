#!/usr/bin/env python3
"""Exercise pool enrollment, work delivery, and GPU share submission locally."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import sys
import threading
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
VERIFIER = ROOT / "pool-verifier/target/release/catecash-pool-verifier"
sys.path.insert(0, str(ROOT))
from solo import double_sha256, header_prefix
from smoke_solo import ADDRESS, template

TEMPLATE = template()


class Handler(BaseHTTPRequestHandler):
    shares = set()

    def log_message(self, *_args):
        pass

    def reply(self, payload):
        data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        route = urlparse(self.path)
        if route.path == "/v1/status":
            return self.reply({"protocol": "catecash-pool/1", "network": "catecash-devnet", "ready": True})
        assert route.path == "/v1/job"
        params = parse_qs(route.query)
        assert params == {"address": [ADDRESS], "worker": ["test-mac"], "plan": ["proportional"]}, params
        return self.reply({
            "network": "catecash-devnet", "plan": "proportional", "job_id": "a1b2c3d4", "height": 7727,
            "header": header_prefix(TEMPLATE).hex(), "nonce_prefix": "12345678",
            "share_target": "ff" * 32,
        })

    def do_POST(self):
        assert self.path == "/v1/share"
        share = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        assert share["address"] == ADDRESS and share["worker"] == "test-mac" and share["plan"] == "proportional"
        assert share["job_id"] == "a1b2c3d4"
        nonce = bytes.fromhex(share["nonce"])
        solution = bytes.fromhex(share["solution"])
        assert len(nonce) == 32 and nonce[:4] == bytes.fromhex("12345678")
        assert len(solution) == 1347 and solution[:3] == b"\xfd\x40\x05"
        assert len(double_sha256(header_prefix(TEMPLATE) + nonce + solution)) == 32
        verified = subprocess.run([str(VERIFIER), header_prefix(TEMPLATE).hex(), nonce.hex(), solution[3:].hex()],
                                  capture_output=True, text=True, timeout=10)
        assert verified.returncode == 0, verified.stderr
        key = (share["job_id"], share["nonce"], share["solution"])
        accepted = key not in self.shares
        self.shares.add(key)
        return self.reply({"accepted": accepted, "reason": "duplicate" if not accepted else None})


def main():
    if not VERIFIER.is_file():
        subprocess.run(["cargo", "build", "--manifest-path", str(ROOT / "pool-verifier/Cargo.toml"),
                        "--release", "--offline"], check=True, cwd=ROOT)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = [sys.executable, str(ROOT / "pool_client.py"),
                "--pool-url", f"http://127.0.0.1:{server.server_port}",
                "--network", "catecash-devnet", "--payout-address", ADDRESS,
                "--worker", "test-mac"]
        checked = subprocess.run(base + ["--check"], cwd=ROOT, text=True, capture_output=True, timeout=10)
        assert checked.returncode == 0, checked.stdout + checked.stderr
        assert "Pool ready" in checked.stdout
        mined = subprocess.run(base + ["--max-shares", "1"], cwd=ROOT, text=True, capture_output=True, timeout=30)
        assert mined.returncode == 0, mined.stdout + mined.stderr
        assert "Accepted share 1" in mined.stdout, mined.stdout
        assert len(Handler.shares) == 1
        print("GPU pool protocol smoke test passed")
    finally:
        server.shutdown()
        thread.join()


if __name__ == "__main__":
    main()
