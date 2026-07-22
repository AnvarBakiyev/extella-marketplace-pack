#!/bin/sh
# Compatibility wrapper for the versioned, hash-verified macOS bootstrap.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec "$ROOT/install-all.sh" "$@"
