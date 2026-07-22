#!/bin/sh
# Double-click compatibility entrypoint. Exact release metadata is mandatory.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec "$ROOT/install-all.sh" "$@"
