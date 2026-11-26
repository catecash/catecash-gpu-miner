# Getting started

This guide builds the Apple Silicon GPU miner from source and connects it to a
Catecash Zebra node that provides `getblocktemplate` and `submitblock` RPCs.
Use a synced node on the network you select. Mining uses a transparent P2PKH
address whose private key you control; the miner never needs that key.

## Requirements

- Apple Silicon Mac with an OpenCL-capable GPU and macOS 13 or later.
- Xcode Command Line Tools (`xcode-select --install`), Rust 1.89 or later,
  and Python 3.9 or later.
- A reachable, synced Catecash Zebra node and its RPC cookie file. Plain HTTP
  RPC is accepted only on loopback; use HTTPS for a remote endpoint.

## 1. Build and check the GPU

```sh
git clone git@github.com:catecash/catecash-gpu-miner.git
cd catecash-gpu-miner
make
make devices
cargo build --locked --manifest-path template-helper/Cargo.toml
cp template-helper/target/debug/catecash-template-helper .
python3 tests/smoke_solo.py
```

`make devices` should list your Apple GPU. The smoke test uses a mock RPC
server and does not submit a block to a live node. To build the native app,
run `mac-app/build.sh`, then open `dist/Catecash Miner.app`.

## 2. Connect to your node

Replace the address below with **your own transparent P2PKH address** for the
selected network. Replace the RPC URL and cookie path with your node's values.
For the optional local devnet Compose setup, see the README's
[local node section](README.md#local-devnet-node-on-the-mac).

```sh
python3 preflight.py \
  --rpc-url http://127.0.0.1:34342 \
  --cookie-file local-node/rpc/.cookie \
  --network catecash-devnet \
  --payout-address YOUR_CATECASH_TRANSPARENT_ADDRESS
```

Preflight checks the node's network and block template. It prints public chain
data, not the RPC cookie. A unified `cate1…` address cannot be used directly
for coinbase; use a transparent receiver that you control.

## 3. Mine

In the app, enter the same RPC URL, network, wallet address, and cookie path.
Click **Test RPC**, then **Start Mining**. **Stop** or closing the window stops
the solver. The intensity slider controls an approximate GPU duty cycle.

For the command line:

```sh
python3 solo.py \
  --rpc-url http://127.0.0.1:34342 \
  --cookie-file local-node/rpc/.cookie \
  --network catecash-devnet \
  --payout-address YOUR_CATECASH_TRANSPARENT_ADDRESS \
  --max-blocks 1
```

Remove `--max-blocks 1` to run continuously; press Ctrl-C to stop. Use
`--device N` to choose a GPU listed by `make devices`. An accepted block is
reported with its height and hash. The node makes the final consensus decision.

## Keep credentials local

Keep RPC cookies, wallet keys, local node state, and built binaries out of the
repository. The included `.gitignore` excludes the standard local paths. Do
not put credentials in an RPC URL or in a Compose file. The local Compose
examples bind RPC to `127.0.0.1` on the host.
