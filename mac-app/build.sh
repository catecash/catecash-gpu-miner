#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
APP="$ROOT/dist/Catecash Miner.app"
export CLANG_MODULE_CACHE_PATH="$ROOT/.build/module-cache"
export SWIFT_MODULE_CACHE_PATH="$ROOT/.build/module-cache"
mkdir -p "$ROOT/.build/module-cache"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$ROOT/mac-app/Info.plist" "$APP/Contents/Info.plist"
cp "$ROOT/solo.py" "$ROOT/preflight.py" "$ROOT/template_work.py" "$ROOT/LICENSE.upstream" "$APP/Contents/Resources/"
cp "$ROOT/sa-solver" "$APP/Contents/Resources/sa-solver"
rm -f "$APP/Contents/Resources/catecash-template-helper"
if [ -f "$ROOT/catecash-template-helper" ]; then
  cp "$ROOT/catecash-template-helper" "$APP/Contents/Resources/catecash-template-helper"
fi
xcrun swiftc -O -parse-as-library -target arm64-apple-macosx13.0 \
  -framework SwiftUI -framework AppKit \
  "$ROOT/mac-app/CatecashMinerApp.swift" -o "$APP/Contents/MacOS/CatecashMiner"
echo "$APP"
