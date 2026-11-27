"""Durable share and reward accounting for separate pool reward plans.

This module calculates liabilities; it does not sign or send payouts.
"""

import hashlib
import sqlite3
import time

from template_work import read_compact


PPLNS_WINDOW = 1000
MATURITY_CONFIRMATIONS = 120


def coinbase_reward_atoms(coinbase_hex):
    data = bytes.fromhex(coinbase_hex)
    if len(data) < 60:
        raise ValueError("coinbase transaction is too short")
    offset = 20
    inputs, offset = read_compact(data, offset)
    if inputs != 1 or data[offset:offset + 32] != b"\x00" * 32 or data[offset + 32:offset + 36] != b"\xff" * 4:
        raise ValueError("expected one coinbase input")
    offset += 36
    script_len, offset = read_compact(data, offset)
    offset += script_len + 4
    outputs, offset = read_compact(data, offset)
    if outputs < 1 or offset + 8 > len(data):
        raise ValueError("coinbase has no payout output")
    return int.from_bytes(data[offset:offset + 8], "little")


def split_reward(reward, counts):
    if reward <= 0 or not counts or any(count <= 0 for count in counts.values()):
        raise ValueError("invalid reward or share counts")
    total = sum(counts.values())
    base = {address: reward * count // total for address, count in counts.items()}
    left = reward - sum(base.values())
    order = sorted(counts, key=lambda address: (-(reward * counts[address] % total), address))
    for address in order[:left]:
        base[address] += 1
    return base


class PoolLedger:
    def __init__(self, path):
        self.db = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS shares (
                id INTEGER PRIMARY KEY, plan TEXT NOT NULL, address TEXT NOT NULL,
                worker TEXT NOT NULL, job_id TEXT NOT NULL, identity TEXT NOT NULL UNIQUE,
                height INTEGER NOT NULL, accepted_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS blocks (
                hash TEXT PRIMARY KEY, plan TEXT NOT NULL, height INTEGER NOT NULL,
                reward_atoms INTEGER NOT NULL, cutoff_share_id INTEGER NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('pending','mature','orphaned')),
                found_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS allocations (
                block_hash TEXT NOT NULL REFERENCES blocks(hash), address TEXT NOT NULL,
                amount_atoms INTEGER NOT NULL, PRIMARY KEY(block_hash,address)
            );
        """)

    def add_share(self, plan, address, worker, job_id, nonce, solution, height):
        identity = hashlib.sha256(job_id.encode() + nonce + solution).hexdigest()
        try:
            cursor = self.db.execute("INSERT INTO shares(plan,address,worker,job_id,identity,height,accepted_at) VALUES(?,?,?,?,?,?,?)",
                                     (plan, address, worker, job_id, identity, height, int(time.time())))
            return cursor.lastrowid
        except sqlite3.IntegrityError:
            return None

    def record_block(self, block_hash, plan, height, reward_atoms):
        if reward_atoms <= 0:
            raise ValueError("block reward must be positive")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            if self.db.execute("SELECT 1 FROM blocks WHERE hash=?", (block_hash,)).fetchone():
                raise ValueError("block already recorded")
            cutoff = self.db.execute("SELECT COALESCE(MAX(id),0) FROM shares WHERE plan=?", (plan,)).fetchone()[0]
            if plan == "proportional":
                previous = self.db.execute("SELECT COALESCE(MAX(cutoff_share_id),0) FROM blocks WHERE plan=? AND state!='orphaned'", (plan,)).fetchone()[0]
                rows = self.db.execute("SELECT address,COUNT(*) FROM shares WHERE plan=? AND id>? AND id<=? GROUP BY address",
                                       (plan, previous, cutoff)).fetchall()
            elif plan == "pplns":
                rows = self.db.execute("SELECT address,COUNT(*) FROM (SELECT address FROM shares WHERE plan=? AND id<=? ORDER BY id DESC LIMIT ?) GROUP BY address",
                                       (plan, cutoff, PPLNS_WINDOW)).fetchall()
            else:
                raise ValueError("invalid reward plan")
            allocations = split_reward(reward_atoms, dict(rows))
            self.db.execute("INSERT INTO blocks(hash,plan,height,reward_atoms,cutoff_share_id,state,found_at) VALUES(?,?,?,?,?,'pending',?)",
                            (block_hash, plan, height, reward_atoms, cutoff, int(time.time())))
            self.db.executemany("INSERT INTO allocations(block_hash,address,amount_atoms) VALUES(?,?,?)",
                                [(block_hash, address, amount) for address, amount in allocations.items()])
            self.db.execute("COMMIT")
            return allocations
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def reconcile_block(self, block_hash, canonical_hash, confirmations):
        row = self.db.execute("SELECT state FROM blocks WHERE hash=?", (block_hash,)).fetchone()
        if row is None:
            raise ValueError("unknown block")
        state = "orphaned" if canonical_hash != block_hash else ("mature" if confirmations >= MATURITY_CONFIRMATIONS else "pending")
        self.db.execute("UPDATE blocks SET state=? WHERE hash=?", (state, block_hash))
        return state

    def balance_atoms(self, address):
        row = self.db.execute("SELECT COALESCE(SUM(a.amount_atoms),0) FROM allocations a JOIN blocks b ON b.hash=a.block_hash WHERE a.address=? AND b.state='mature'",
                              (address,)).fetchone()
        return row[0]

    def block_allocations(self, block_hash):
        return dict(self.db.execute("SELECT address,amount_atoms FROM allocations WHERE block_hash=?", (block_hash,)).fetchall())

    def blocks_to_reconcile(self):
        return self.db.execute("SELECT hash,height FROM blocks ORDER BY height").fetchall()
