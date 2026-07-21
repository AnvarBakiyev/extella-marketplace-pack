#!/bin/sh
# Native fail-closed bootstrap for Extella Client on macOS Intel and Apple Silicon.
set -eu

PYTHON_VERSION="3.12.13"
UV_VERSION="0.11.30"
BUNDLE_PATH="${EXTELLA_BUNDLE_PATH:-}"
BUNDLE_URL="${EXTELLA_BUNDLE_URL:-}"
BUNDLE_SHA256="${EXTELLA_BUNDLE_SHA256:-}"
BUNDLE_BYTES="${EXTELLA_BUNDLE_BYTES:-}"
NO_START=0
VERIFY_ONLY=0
MATRIX_PHASE=""
MATRIX_RESULT=""
RELEASE_MANIFEST=""

usage() {
  printf '%s\n' "Usage: $0 (--bundle PATH | --url HTTPS_URL) --sha256 HEX --bytes N [--no-start] [--verify-only] [--matrix-phase baseline|previous-release --matrix-result PATH --release-manifest PATH]"
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --bundle) [ "$#" -ge 2 ] || { usage >&2; exit 2; }; BUNDLE_PATH=$2; shift 2 ;;
    --url) [ "$#" -ge 2 ] || { usage >&2; exit 2; }; BUNDLE_URL=$2; shift 2 ;;
    --sha256) [ "$#" -ge 2 ] || { usage >&2; exit 2; }; BUNDLE_SHA256=$2; shift 2 ;;
    --bytes) [ "$#" -ge 2 ] || { usage >&2; exit 2; }; BUNDLE_BYTES=$2; shift 2 ;;
    --no-start) NO_START=1; shift ;;
    --verify-only) VERIFY_ONLY=1; shift ;;
    --matrix-phase) [ "$#" -ge 2 ] || { usage >&2; exit 2; }; MATRIX_PHASE=$2; shift 2 ;;
    --matrix-result) [ "$#" -ge 2 ] || { usage >&2; exit 2; }; MATRIX_RESULT=$2; shift 2 ;;
    --release-manifest) [ "$#" -ge 2 ] || { usage >&2; exit 2; }; RELEASE_MANIFEST=$2; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Unknown argument: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done

# This check must stay before mktemp, downloads, directory creation, or any
# other mutation. Unsupported systems are a hard stop, never partial success.
if [ "$(uname -s 2>/dev/null || true)" != "Darwin" ]; then
  printf '%s\n' "Extella Client supports only macOS x86_64/arm64 and Windows 11 x64. This bootstrap is for macOS. No changes were made." >&2
  exit 3
fi

ARCH=$(uname -m 2>/dev/null || true)
case "$ARCH" in
  arm64)
    PLATFORM="macos-arm64"
    UV_ARCHIVE="uv-aarch64-apple-darwin.tar.gz"
    UV_BYTES="22543508"
    UV_SHA256="9bed3567d496d8dab84ecf7a1247551ac94ef1baaebb7b65df008dd93e9dc357"
    ;;
  x86_64)
    PLATFORM="macos-x86_64"
    UV_ARCHIVE="uv-x86_64-apple-darwin.tar.gz"
    UV_BYTES="24248677"
    UV_SHA256="ce285fbbfbe294b1e1bc6c87c8b59d9622b85383b88b2b132a2df5c73e83d7c1"
    ;;
  *)
    printf 'Unsupported macOS architecture: %s. Required: x86_64 or arm64. No changes were made.\n' "$ARCH" >&2
    exit 3
    ;;
esac

printf '%s' "$BUNDLE_SHA256" | grep -Eq '^[0-9a-fA-F]{64}$' || { printf '%s\n' "A 64-character bundle SHA-256 is required." >&2; exit 2; }
case "$BUNDLE_BYTES" in
  ''|*[!0-9]*|0) printf '%s\n' "A positive bundle byte size is required." >&2; exit 2 ;;
esac
if [ -n "$BUNDLE_PATH" ] && [ -n "$BUNDLE_URL" ]; then
  printf '%s\n' "Choose either --bundle or --url, not both." >&2
  exit 2
fi
if [ -z "$BUNDLE_PATH" ] && [ -z "$BUNDLE_URL" ]; then
  printf '%s\n' "No release bundle was specified. Raw main branches are intentionally unsupported." >&2
  usage >&2
  exit 2
fi
if { [ -n "$MATRIX_PHASE" ] || [ -n "$MATRIX_RESULT" ] || [ -n "$RELEASE_MANIFEST" ]; } && { [ -z "$MATRIX_PHASE" ] || [ -z "$MATRIX_RESULT" ] || [ -z "$RELEASE_MANIFEST" ]; }; then
  printf '%s\n' "Matrix evidence requires --matrix-phase, --matrix-result, and --release-manifest together." >&2
  exit 2
fi
if [ -n "$MATRIX_PHASE" ]; then
  case "$MATRIX_PHASE" in baseline|previous-release) ;; *) printf '%s\n' "Native bootstrap matrix phase must be baseline or previous-release." >&2; exit 2 ;; esac
fi
if [ -n "$MATRIX_PHASE" ] && [ -z "$BUNDLE_PATH" ]; then
  printf '%s\n' "Matrix evidence requires the local candidate passed with --bundle." >&2
  exit 2
fi
if [ -n "$BUNDLE_URL" ]; then
  case "$BUNDLE_URL" in https://*) ;; *) printf '%s\n' "Bundle URL must use HTTPS." >&2; exit 2 ;; esac
fi
command -v curl >/dev/null 2>&1 || { printf '%s\n' "curl is required by the native bootstrap." >&2; exit 2; }
command -v shasum >/dev/null 2>&1 || { printf '%s\n' "shasum is required by the native bootstrap." >&2; exit 2; }

WORK=$(mktemp -d "${TMPDIR:-/tmp}/extella-client.XXXXXX")
cleanup() { rm -rf "$WORK"; }
trap cleanup EXIT HUP INT TERM
BUNDLE="$WORK/extella-client.zip"

if [ -n "$BUNDLE_PATH" ]; then
  [ -f "$BUNDLE_PATH" ] || { printf 'Bundle not found: %s\n' "$BUNDLE_PATH" >&2; exit 2; }
  cp "$BUNDLE_PATH" "$BUNDLE"
else
  curl --fail --location --silent --show-error --proto '=https' --tlsv1.2 "$BUNDLE_URL" -o "$BUNDLE"
fi

actual_bytes=$(wc -c < "$BUNDLE" | tr -d '[:space:]')
[ "$actual_bytes" = "$BUNDLE_BYTES" ] || { printf 'Bundle size mismatch: expected %s, got %s.\n' "$BUNDLE_BYTES" "$actual_bytes" >&2; exit 2; }
actual_sha=$(shasum -a 256 "$BUNDLE" | awk '{print $1}')
[ "$actual_sha" = "$(printf '%s' "$BUNDLE_SHA256" | tr 'A-F' 'a-f')" ] || { printf '%s\n' "Bundle SHA-256 mismatch. No Extella files were changed." >&2; exit 2; }

UV_URL="https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/${UV_ARCHIVE}"
UV_PACKAGE="$WORK/$UV_ARCHIVE"
curl --fail --location --silent --show-error --proto '=https' --tlsv1.2 "$UV_URL" -o "$UV_PACKAGE"
uv_actual_bytes=$(wc -c < "$UV_PACKAGE" | tr -d '[:space:]')
[ "$uv_actual_bytes" = "$UV_BYTES" ] || { printf 'uv size mismatch: expected %s, got %s.\n' "$UV_BYTES" "$uv_actual_bytes" >&2; exit 2; }
uv_actual_sha=$(shasum -a 256 "$UV_PACKAGE" | awk '{print $1}')
[ "$uv_actual_sha" = "$UV_SHA256" ] || { printf '%s\n' "uv SHA-256 mismatch." >&2; exit 2; }

mkdir "$WORK/uv"
tar -xzf "$UV_PACKAGE" -C "$WORK/uv"
UV_BIN=$(find "$WORK/uv" -type f -name uv -perm -u+x | head -n 1)
[ -n "$UV_BIN" ] || { printf '%s\n' "Verified uv archive did not contain an executable." >&2; exit 2; }

PYROOT="$WORK/python"
"$UV_BIN" python install "$PYTHON_VERSION" --install-dir "$PYROOT" --no-bin --no-registry
PYTHON=$(find "$PYROOT" -type f -name python3.12 -perm -u+x | head -n 1)
[ -n "$PYTHON" ] || { printf '%s\n' "Managed Python 3.12 was not installed." >&2; exit 2; }
"$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info[:3] == (3, 12, 13) else 2)'

EXTRACTED="$WORK/bundle"
mkdir "$EXTRACTED"
"$PYTHON" - "$BUNDLE" "$EXTRACTED" <<'PY'
import pathlib, stat, sys, zipfile
archive, target = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
with zipfile.ZipFile(archive) as source:
    for item in source.infolist():
        name = item.filename
        parts = pathlib.PurePosixPath(name).parts
        mode = (item.external_attr >> 16) & 0o170000
        if not name or name.startswith(("/", "\\")) or "\\" in name or ".." in parts or mode == stat.S_IFLNK:
            raise SystemExit("unsafe path or symlink in Extella bundle")
    source.extractall(target)
PY

INSTALLER="$EXTRACTED/payload/marketplace/installer/client_install.py"
[ -f "$INSTALLER" ] || { printf '%s\n' "Verified bundle has no client installer." >&2; exit 2; }
RUNNER="$EXTRACTED/payload/marketplace/tools/external_matrix.py"
if [ -n "$MATRIX_PHASE" ]; then
  [ -f "$RELEASE_MANIFEST" ] || { printf '%s\n' "Release manifest not found." >&2; exit 2; }
  [ -f "$RUNNER" ] || { printf '%s\n' "Verified bundle has no external matrix runner." >&2; exit 2; }
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$EXTRACTED/payload/marketplace" "$PYTHON" -c 'from pathlib import Path; from installer.bundle import verify_bundle; import sys; print(verify_bundle(Path(sys.argv[1])))' "$EXTRACTED"
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$EXTRACTED/payload/marketplace" "$PYTHON" "$RUNNER" \
    --phase "$MATRIX_PHASE" \
    --expected-platform "$PLATFORM" \
    --candidate "$BUNDLE_PATH" \
    --release-manifest "$RELEASE_MANIFEST" \
    --result "$MATRIX_RESULT"
fi
if [ "$VERIFY_ONLY" -eq 1 ]; then
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$EXTRACTED/payload/marketplace" "$PYTHON" -c 'from pathlib import Path; from installer.bundle import verify_bundle; import sys; print(verify_bundle(Path(sys.argv[1])))' "$EXTRACTED"
  printf 'Verified Extella bootstrap, managed Python, and bundle for %s. No client files were changed.\n' "$PLATFORM"
  exit 0
fi
set -- "$INSTALLER" --bundle-root "$EXTRACTED" --bootstrap-python-root "$PYROOT"
[ "$NO_START" -eq 0 ] || set -- "$@" --no-start
printf 'Installing Extella Client %s on %s…\n' "$BUNDLE_SHA256" "$PLATFORM"
PYTHONDONTWRITEBYTECODE=1 "$PYTHON" "$@"
