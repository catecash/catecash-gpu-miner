#!/bin/sh
set -eu
socat TCP-LISTEN:34342,bind=0.0.0.0,reuseaddr,fork TCP:127.0.0.1:34352 &
exec /usr/local/bin/zebrad "$@"
