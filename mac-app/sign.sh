#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
APP="$ROOT/dist/Catecash Miner.app"
IDENTITY=${1:?usage: mac-app/sign.sh 'Apple Development: ...' or 'Developer ID Application: ...'}
codesign --force --options runtime --sign "$IDENTITY" "$APP/Contents/Resources/sa-solver"
codesign --force --options runtime --sign "$IDENTITY" "$APP/Contents/Resources/catecash-template-helper"
codesign --force --options runtime --sign "$IDENTITY" "$APP"
codesign --verify --deep --strict --verbose=2 "$APP"
