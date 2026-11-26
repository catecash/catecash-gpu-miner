#!/usr/bin/env python3
"""Check that a Catecash node can supply mining work without exposing secrets."""

import argparse
import base64
import json
from pathlib import Path
import sys
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


NETWORKS = {"catecash-mainnet", "catecash-testnet", "catecash-devnet"}


def rpc(url: str, cookie: Optional[Path], method: str, params: list):
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    headers = {"Content-Type": "application/json"}
    if cookie is not None:
        user_password = cookie.read_text(encoding="utf-8").strip()
        if ":" not in user_password:
            raise ValueError("RPC cookie has no user:password separator")
        authorization = base64.b64encode(user_password.encode("utf-8")).decode("ascii")
        headers["Authorization"] = f"Basic {authorization}"
    request = Request(url, payload, headers)
    with urlopen(request, timeout=15) as response:
        result = json.load(response)
    if result.get("error"):
        raise RuntimeError(f"{method}: {result['error']}")
    return result["result"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rpc-url", required=True)
    parser.add_argument("--cookie-file", type=Path)
    parser.add_argument("--network", required=True, choices=sorted(NETWORKS))
    parser.add_argument("--payout-address")
    args = parser.parse_args()

    url = urlparse(args.rpc_url)
    if url.scheme == "http" and url.hostname not in {"127.0.0.1", "localhost", "::1"}:
        parser.error("HTTP RPC must use loopback")
    if url.scheme not in {"http", "https"} or url.hostname is None:
        parser.error("RPC must use loopback HTTP or HTTPS")

    try:
        info = rpc(args.rpc_url, args.cookie_file, "getblockchaininfo", [])
        network = str(info.get("chain", "")).lower()
        if network != args.network:
            raise ValueError(f"unexpected network {network!r}; expected {args.network!r}")
        template = rpc(args.rpc_url, args.cookie_file, "getblocktemplate", [])
        if args.payout_address:
            from template_work import prepare_template
            template = prepare_template(template, args.payout_address, network)
        print(json.dumps({
            "network": network,
            "node_height": info.get("blocks"),
            "template_height": template.get("height"),
            "previous_block_hash": template.get("previousblockhash"),
            "target": template.get("target"),
            "transactions": len(template.get("transactions", [])),
        }, indent=2))
    except (OSError, ValueError, KeyError, RuntimeError, HTTPError, URLError) as error:
        print(f"preflight failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
