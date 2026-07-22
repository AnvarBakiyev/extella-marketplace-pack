# Extella Client release entrypoints

The only supported native bootstraps are:

- `install-all.sh` — macOS x86_64 and arm64
- `install-all.ps1` — Windows 11 x64

Both require an exact versioned bundle URL/path, SHA-256, and byte size. They
reject unsupported platforms before mutation and never fetch executable code
from an unpinned `main` branch.

The release itself is built and gated from the separate integration repository.
See the repository `README.md`, `release/release-manifest.json`, and
`release/EXTERNAL_MATRIX.md` for the build, verification, clean-machine matrix,
and approval sequence.
