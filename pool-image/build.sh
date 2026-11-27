#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT HUP INT TERM
mkdir -p "$stage/pool-verifier/src"
cp "$root/pool-image/Dockerfile" "$stage/Dockerfile"
cp "$root/pool_server.py" "$root/pool_accounting.py" "$root/pool_client.py" \
   "$root/preflight.py" "$root/solo.py" "$root/template_work.py" "$stage/"
cp "$root/pool-verifier/Cargo.toml" "$root/pool-verifier/Cargo.lock" "$stage/pool-verifier/"
cp "$root/pool-verifier/src/main.rs" "$stage/pool-verifier/src/"
docker build -t catecash-pool:local "$stage"
