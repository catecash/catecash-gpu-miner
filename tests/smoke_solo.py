#!/usr/bin/env python3
"""Exercise GPU work, block assembly, proposal, and submit against mock RPC."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from template_work import prepare_template

COINBASE = ("0600008098b684d8b4ee3bea000000002f1e0000010000000000000000000000000000000000000000000000000000000000000000"
            "ffffffff08022f1e04f09fa693ffffffff010088526a740000001976a914ac1b5dc056076593412d9ad3881e793c1fbe448d88ac00000000")
ADDRESS = "yPeC241BhV8S3oRB58xPobSFzJXkhYxwhKK"


def template():
    now = int(time.time())
    return {
        "height": 7727, "version": 4, "previousblockhash": bytes(range(32)).hex(),
        "defaultroots": {
            "merkleroot": "cf4b6edeb308e39dbc816a97ffd5ac1d90e37d6c3750521650f9bd9ccfd3dfe0",
            "chainhistoryroot": "89370311a507b5b5282485566049ef8990181db679d423fda5162d07cbf4208f",
            "authdataroot": "7019bfe19adb1531d10b412d2e18027e428e0b7c3c8e1d827d29b453636c7d3f",
        },
        "blockcommitmentshash": "6775645f5a9e29521dedc15d6fda9647aa3d96b7796a3889307c410ab435c429",
        "curtime": now, "mintime": now - 1, "maxtime": now + 90,
        "bits": "207fffff", "target": "ff" * 32,
        "coinbasetxn": {"data": COINBASE}, "transactions": [],
    }


class Handler(BaseHTTPRequestHandler):
    calls = []
    node_payout = False

    def log_message(self, *_args):
        pass

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        method = request["method"]
        self.calls.append(method)
        if method == "getblockchaininfo":
            result = {"chain": "catecash-devnet", "blocks": 0}
        elif method == "getblocktemplate" and request["params"] and request["params"][0].get("mode") == "proposal":
            result = None
        elif method == "getblocktemplate":
            assert request["params"] == []
            result = template()
        elif method == "submitblock":
            block = bytes.fromhex(request["params"][0])
            expected = template() if self.node_payout else prepare_template(template(), ADDRESS, "catecash-devnet")
            assert len(block) == 108 + 32 + 1347 + 1 + len(bytes.fromhex(COINBASE))
            assert block[:4] == b"\x04\x00\x00\x00"
            assert block[4:36] == bytes(range(32))[::-1]
            assert block[36:68] == bytes.fromhex(expected["defaultroots"]["merkleroot"])[::-1]
            assert block[68:100] == bytes.fromhex(expected["blockcommitmentshash"])[::-1]
            assert block[104:108] == bytes.fromhex("207fffff")[::-1]
            assert block[140:143] == b"\xfd\x40\x05"
            assert block[-len(bytes.fromhex(COINBASE)):] == bytes.fromhex(expected["coinbasetxn"]["data"])
            result = None
        else:
            raise AssertionError(method)
        data = json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result, "error": None}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main():
    Handler.node_payout = "--node-payout" in sys.argv
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory() as directory:
            cookie = Path(directory) / "rpc.cookie"
            cookie.write_text("mock:credential", encoding="utf-8")
            command = [
                sys.executable, str(ROOT / "solo.py"),
                "--rpc-url", f"http://127.0.0.1:{server.server_port}",
                "--cookie-file", str(cookie), "--network", "catecash-devnet",
                "--max-blocks", "1", "--intensity", "30",
            ]
            if not Handler.node_payout:
                command += ["--payout-address", ADDRESS]
            result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=20)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "Accepted block at height 7727" in result.stdout, result.stdout
        assert "getblocktemplatetoaddress" not in Handler.calls, Handler.calls
        assert "submitblock" in Handler.calls, Handler.calls
        print("GPU solo RPC smoke test passed")
    finally:
        server.shutdown()
        thread.join()


if __name__ == "__main__":
    main()
