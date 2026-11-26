"""Apply a transparent payout address to a standard Zebra block template."""

import hashlib
import json
from pathlib import Path
import subprocess


PREFIXES = {
    "catecash-mainnet": b"\x06\x84",
    "catecash-testnet": b"\x07\x84",
    "catecash-devnet": b"\x1f\xc0",
}
ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def payout_script(address, network):
    value = 0
    for character in address:
        if character not in ALPHABET:
            raise ValueError("wallet address is not Base58")
        value = value * 58 + ALPHABET.index(character)
    decoded = value.to_bytes((value.bit_length() + 7) // 8, "big")
    decoded = b"\x00" * (len(address) - len(address.lstrip("1"))) + decoded
    if len(decoded) != 26 or hashlib.sha256(hashlib.sha256(decoded[:-4]).digest()).digest()[:4] != decoded[-4:]:
        raise ValueError("wallet address has an invalid length or checksum")
    if decoded[:2] != PREFIXES[network]:
        raise ValueError("wallet address must be a transparent P2PKH address for the selected network")
    return b"\x76\xa9\x14" + decoded[2:22] + b"\x88\xac"


def read_compact(data, offset):
    marker = data[offset]
    offset += 1
    if marker < 253:
        return marker, offset
    width = {253: 2, 254: 4, 255: 8}[marker]
    if offset + width > len(data):
        raise ValueError("truncated coinbase transaction")
    return int.from_bytes(data[offset:offset + width], "little"), offset + width


def replace_payout(coinbase_hex, script):
    data = bytearray.fromhex(coinbase_hex)
    if len(data) < 21 or int.from_bytes(data[:4], "little") not in (0x80000005, 0x80000006):
        raise ValueError("unsupported coinbase transaction version")
    offset = 20  # version, version group, branch, lock time, expiry height
    input_count, offset = read_compact(data, offset)
    if input_count != 1:
        raise ValueError("expected one coinbase input")
    if offset + 36 > len(data) or data[offset:offset + 32] != b"\x00" * 32 or data[offset + 32:offset + 36] != b"\xff" * 4:
        raise ValueError("first input is not a coinbase input")
    offset += 36
    script_length, offset = read_compact(data, offset)
    offset += script_length + 4  # scriptSig and sequence
    if offset > len(data):
        raise ValueError("truncated coinbase input")
    output_count, offset = read_compact(data, offset)
    if output_count < 1 or offset + 8 > len(data):
        raise ValueError("coinbase has no payout output")
    offset += 8
    length, offset = read_compact(data, offset)
    if length != 25 or offset + length > len(data):
        raise ValueError("first coinbase output is not P2PKH")
    old = bytes(data[offset:offset + length])
    if old[:3] != b"\x76\xa9\x14" or old[-2:] != b"\x88\xac":
        raise ValueError("first coinbase output is not P2PKH")
    data[offset:offset + length] = script
    return data.hex()


def roots(template, coinbase_hex):
    helper = Path(__file__).resolve().parent / "catecash-template-helper"
    if not helper.is_file():
        raise FileNotFoundError("template-helper is missing; build the miner first")
    request = {
        "transactions": [coinbase_hex] + [tx["data"] for tx in template["transactions"]],
        "chainhistoryroot": template["defaultroots"]["chainhistoryroot"],
    }
    result = subprocess.run([str(helper)], input=json.dumps(request), text=True, capture_output=True)
    if result.returncode:
        raise ValueError(result.stderr.strip() or "template helper failed")
    return json.loads(result.stdout)


def prepare_template(template, address, network):
    original = roots(template, template["coinbasetxn"]["data"])
    if original["merkleroot"] != template["defaultroots"]["merkleroot"]:
        raise ValueError("node template Merkle root did not match its transactions")
    if original["blockcommitmentshash"] != template["blockcommitmentshash"]:
        raise ValueError("node template block commitment did not match its transactions")
    changed = replace_payout(template["coinbasetxn"]["data"], payout_script(address, network))
    updated = roots(template, changed)
    result = dict(template)
    result["coinbasetxn"] = dict(template["coinbasetxn"], data=changed,
                                  hash=updated["coinbase_hash"],
                                  authdigest=updated["coinbase_authdigest"])
    result["defaultroots"] = dict(template["defaultroots"],
                                  merkleroot=updated["merkleroot"],
                                  authdataroot=updated["authdataroot"],
                                  blockcommitmentshash=updated["blockcommitmentshash"])
    result["blockcommitmentshash"] = updated["blockcommitmentshash"]
    return result
