#!/bin/sh
# Compatibility wrapper: the unified verified client installer is canonical.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec "$ROOT/toolbar/install-all.sh" "$@"
