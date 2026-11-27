# Catecash GPU Miner for macOS

Native macOS app for Catecash mining on Apple Silicon. Solo mode uses the Mac's
GPU through OpenCL to solve Equihash (200,9), obtains work from Catecash Zebra's
`getblocktemplate`, checks candidate blocks with proposal mode, and sends them
with `submitblock`. Pool mode is an experimental client for a compatible pool
service. The miner lives outside the Zebra repository.

Apple still supports GPU OpenCL on Apple Silicon, although [the API is
deprecated](https://developer.apple.com/documentation/Apple-Silicon/porting-your-macos-apps-to-apple-silicon).
This backend uses Marc Bevand's [SILENTARMY](https://github.com/mbevand/silentarmy)
Equihash solver at commit `c6a9ca85a81708589c904d2cbf3c665cd7ce5fa0`,
adapted to build on macOS ARM64. The upstream solver's MIT license is in
`LICENSE.upstream`.

**[Getting started](GETTING_STARTED.md)** covers the build, node connection,
first RPC check, and mining commands. This repository contains source code;
generated app bundles, solver binaries, local node state, and RPC credentials
are excluded.

**[Pool plan](POOL_PLAN.md)** describes the new Pool mode and the server,
share verification, and payout work required before a public pool launch.
The app can connect to a compatible prototype pool and submit GPU shares;
the included mock pool is only for local testing and never pays miners.

## Build and verify

Requires Xcode Command Line Tools (or Xcode), Python 3.9+, and macOS with an
OpenCL-capable Apple GPU. No Python packages or wallet keys are required.

```sh
make
make devices
python3 tests/smoke_solo.py --node-payout
python3 tests/smoke_pool.py
mac-app/build.sh
```

`make devices` should show the Apple GPU as device 0. The smoke test runs the
GPU solver against a local mock RPC server, assembles a block, and exercises
proposal and submit calls. It does not change a real chain.

The default path uses the payout address configured on your Zebra node. To
override that payout in the miner, place a compatible Catecash Zebra checkout
at `../catecash-zebra`. This optional path also requires Rust 1.89+:

```sh
cargo build --locked --manifest-path template-helper/Cargo.toml
cp template-helper/target/debug/catecash-template-helper .
python3 tests/smoke_solo.py
mac-app/build.sh
```

The Rust helper needs the local `zebra-chain` and `vendor/zcash_*` crates from
that checkout.

Open the locally built `dist/Catecash Miner.app` to enter the RPC URL, network,
and optional RPC cookie file. Leave the payout override blank to use the node's
configured mining address. **Test RPC** checks the connection and block
template. **Start Mining** and **Stop** control the GPU
process. The GPU duty cycle slider defaults to 50% and can be set from 10% to
100%. The solver rests between completed GPU work units to reduce average GPU
activity. A mining burst can still reach full GPU usage; Apple GPUs do not
expose a way to reserve a fixed fraction of GPU cores for this app.
Closing the window stops mining. Settings contain only the public wallet
address, endpoint, and cookie file path, never the cookie contents.

To rebuild after changing code, run `mac-app/build.sh`. For distribution,
sign the bundle with your own Developer ID Application identity and notarize it.
`mac-app/sign.sh 'Developer ID Application: YOUR IDENTITY'` signs a built bundle.

## Mine a Catecash node

The node must be synchronized and expose Zebra's standard `getblocktemplate`,
proposal, and `submitblock` RPCs. Configure a Catecash transparent P2PKH mining
address you control on the node. With the optional helper, entering an override
in the app makes the miner rewrite the first coinbase output locally and
recalculate transaction and block commitments before mining. Keep your wallet's
private key in separate local storage.

## Local devnet node on the Mac

The `local-node/` Compose file runs Catecash Zebra in Docker. Its RPC is
published only on `127.0.0.1:34342`, requires the local cookie, and does not
use the hosted node's RPC. It connects to a devnet peer over the normal P2P
protocol and verifies its own chain state. No new Zebra RPC methods are enabled.

Place a compatible Linux ARM64 `zebrad` binary at `local-node/image/zebrad`
before the first build. This Mac's local image was built from the existing
non-mining node binary on the user's hosted machine; its SHA-256 is
`9ebd25613f3f96553ebcd1fc053463200c04eefc48d8dd43e9ad276460143a67`.
The binary is ignored by Git and never receives RPC credentials in the image.
The container runs as this Mac's user (UID 501, GID 20). The node state and
cookie remain in ignored local directories.

Copy `local-node/zebrad.toml.example` to `local-node/zebrad.toml`, then set
`mining.miner_address` to your own devnet transparent P2PKH address before
starting the node. The local config is ignored by Git.

```sh
docker compose -f local-node/compose.yaml up --build -d
docker compose -f local-node/compose.yaml logs -f node
```

Wait for the node to reach the chain tip. The app uses
`local-node/rpc/.cookie` and `http://127.0.0.1:34342`.

```sh
python3 preflight.py --rpc-url http://127.0.0.1:34342 \
  --cookie-file local-node/rpc/.cookie --network catecash-devnet
python3 solo.py --rpc-url http://127.0.0.1:34342 \
  --cookie-file local-node/rpc/.cookie --network catecash-devnet \
  --max-blocks 1
```

The cookie and state directories are ignored by Git. RPC uses loopback HTTP.
Use `--device N` to select a GPU. Omit `--max-blocks 1` to mine continuously;
Ctrl-C stops the solver.

The miner refreshes work every two seconds, validates the node's network name,
uses the template's transactions and a locally updated coinbase, verifies the block
hash against the target, and checks the block proposal before submission.
The node performs final consensus validation. On November 25, 2026, an
isolated two-node devnet run accepted a height-one block mined by the M2 Ultra;
the second node synchronized to the same height. The test used temporary chain
state and a test payout address with no known private key.

## Local Catecash mainnet candidate

`local-mainnet/` runs a separate local node on `127.0.0.1:34332`, with its own
chain state and RPC cookie. It uses the documented candidate binary from the
operator's mainnet host, SHA-256
`742d7f0a484dd0514bec52fd7970da82592d6e1642395fcbc88a32d971e80f6e`.
The binary is ignored by Git and the cookie is never included in the image.
The node's genesis must be
`050bf7476db81684aeb38337fc931bd8bc4480fde43fb0a14fef172f85c5c323`.
This is the project's private mainnet **candidate** chain, not a public release.
Copy `local-mainnet/zebrad.toml.example` to `local-mainnet/zebrad.toml` and
set `mining.miner_address` to your own mainnet transparent P2PKH address before
starting the node.

```sh
docker compose -f local-mainnet/compose.yaml up --build -d
python3 preflight.py --rpc-url http://127.0.0.1:34332 \
  --cookie-file local-mainnet/rpc/.cookie --network catecash-mainnet
```

The miner requires a transparent P2PKH address for coinbase payouts. A unified
`cate1…` address cannot be entered directly; if it contains a transparent
receiver, enter that receiver instead. The unified address provided for this
test had none. The operator supplied a `Ca…` receiver
with the same 20-byte key hash as the Devnet address. On November 25, 2026,
the local node accepted one GPU-mined candidate block at height 6,036 paying
that receiver; the block later had three local confirmations.
