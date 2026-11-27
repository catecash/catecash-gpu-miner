# Catecash mining pool plan

## Goal

Let a Mac owner enter a Catecash transparent payout address, join a pool, and
contribute GPU work. The pool must validate each share, account for it, and pay
miners according to published rules. The existing solo miner remains available.

## Milestones

1. **Mac client prototype (this change).** Add Pool mode to the native app.
   It checks a pool's protocol and network, requests work, mines with the
   bundled solver, and submits shares. A local mock exercises this flow. It
   does not create balances or payments.
2. **Pool service and verifier.** A development coordinator and Equihash
   verifier are now in source; the coordinator is closed by default and does
   not pay miners. Run the eventual public service in containers. Fetch fresh
   templates from an isolated, synchronized Catecash Zebra node. Allocate a
   unique four-byte nonce prefix to each active worker job. Keep immutable job
   records and expire stale jobs. Verify the Equihash (200,9) solution with a
   consensus-compatible verifier, check the 256-bit share target and duplicate
   submissions, then run block candidates through Zebra proposal mode and
   `submitblock`. Do not treat a hash-only check as share validation.
3. **Accounting and payouts.** Accepted shares and block allocations now have
   a prototype SQLite ledger. It credits a block only after 120 confirmations
   and removes credits if a recorded block is orphaned. The operator requested
   both proportional and PPLNS
   plans. Treat them as separate pools, each with its own work, accepted-share
   window, block attribution, and balance ledger. A miner can select a plan
   and their own public payout address. Publish the exact rules, fee, minimum
   payout, maturity and reorg policy before accepting public miners. Add a
   chain reconciler, payout signer, payment receipts, and independent balance
   audit. The operator wallet is now verified and stored encrypted in the Mac
   Keychain. Implement signing on the operator's Mac and keep the key off the
   pool service and other miners' clients.
4. **Release gate.** Rehearse end to end on devnet and testnet with multiple
   workers. Test stale and duplicate shares, invalid Equihash, nonce prefix
   collisions, chain reorganizations, node outages, reconnects, rate limits,
   accounting replay, and payout reconciliation. Publish endpoint, terms,
   supported versions, and signed/notarized Mac app only after this gate.

## Prototype protocol: `catecash-pool/1`

All requests use JSON over HTTPS; loopback HTTP is allowed for local testing.
The Mac app stores the pool URL, network, public payout address, worker name,
reward plan, and optional public operator receiving address. An operator WIF
can be imported through the GUI and remains in this Mac's Keychain. No wallet
key is sent to the pool.

| Request | Response |
| --- | --- |
| `GET /v1/status` | `protocol`, `network`, `ready` |
| `GET /v1/job?address=...&worker=...&plan=...` | `network`, `plan` (`proportional` or `pplns`), hexadecimal `job_id` (up to 32 characters), `height`, 108-byte `header` hex, four-byte `nonce_prefix` hex, and 32-byte `share_target` hex in display order |
| `POST /v1/share` | Send `address`, `worker`, `plan`, `job_id`, full 32-byte `nonce`, and 1,347-byte encoded `solution` hex; receive `accepted` and optional `reason` |

The server must bind each job to its worker and payout address and validate the
header, nonce prefix, solution, target, and job freshness itself. The client
checks basic shapes and the share hash before sending; those checks are not a
substitute for server validation. The server must keep both its share target
and the actual network target; a share is not necessarily a block.

## Decisions for the public pool

- Operator fee for each plan; default proposal is 0% for both.
- Minimum payout and payout interval.
- Public pool hostname and whether account-free payout address identity is
  sufficient or worker authentication is needed.
- Share difficulty policy and minimum supported Mac GPU performance.
