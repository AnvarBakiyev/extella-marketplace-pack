# Extella Client release package

This repository is the canonical packaging source for the versioned Extella
Client distribution. The supported client includes the toolbar, Activity
Center, Adoption Wizard, bundled experts, account KV objects, local services,
and the shared dependency/runtime layer.

## Supported platforms

Only these targets are in the release contract:

- macOS x86_64 (Intel)
- macOS arm64 (Apple Silicon)
- Windows 11 x64

Linux, Windows 10, and Windows ARM are intentionally unsupported. Native
bootstraps reject them before creating temporary directories, downloading a
bundle, or changing client files.

## Install a published release

Never install from a raw `main` branch. Take the bundle URL, SHA-256, and exact
byte size from one published Extella Client release.

macOS:

```sh
./toolbar/install-all.sh \
  --url "https://RELEASE-URL/extella-client-VERSION.zip" \
  --sha256 "64_HEX_CHARACTERS" \
  --bytes "EXACT_BYTE_SIZE"
```

Windows 11 x64 (PowerShell):

```powershell
.\toolbar\install-all.ps1 `
  -BundleUrl "https://RELEASE-URL/extella-client-VERSION.zip" `
  -BundleSha256 "64_HEX_CHARACTERS" `
  -BundleBytes EXACT_BYTE_SIZE
```

For an offline/local candidate, use `--bundle` on macOS or `-BundlePath` on
Windows with the same hash and size checks. `--verify-only`/`-VerifyOnly`
validates the bootstrap, managed Python, and bundle without installing.

The legacy `install.py`, standalone Activity Center installers, and raw toolbar
updaters are retired and fail without mutation. `install_toolbar.sh`,
`toolbar/install.sh`, and their Windows counterparts are compatibility wrappers
around the unified native bootstraps.

## Release contract

- `release/release-manifest.json` is the single versioned release contract.
- `release/plugins/*.json` contains schema-validated bundled plugin contracts.
- `release/expert-classification.json` classifies every shipped expert.
- `release/catalog-policy.json` marks external catalogs as third-party and
  unverified. The three Extella-managed runtime candidates are declared
  separately as `supported_on_demand` and remain visibly marked as candidates
  until their complete external matrix passes.
- `runtime/extella_runtime/ensure_tool.py` is the shared dependency resolver.
- `installer/client_install.py` and `installer/client_uninstall.py` own the base
  client. `installer/plugin_lifecycle.py` is the single allow-listed,
  transactional install/uninstall entrypoint for supported on-demand programs;
  toolbar cards reach it only through Activity Center's token-protected local
  API.

Builds are allowlisted and deterministic:

```sh
python3 tools/build_client_bundle.py \
  --toolbar-root ../toolbar \
  --wizard-root ../wizard \
  --output artifacts/extella-client-VERSION.zip
```

The builder refuses dirty source repositories and records the exact marketplace,
toolbar, and wizard Git SHAs in `bundle-manifest.json`.

Run the local gate with the exact candidate:

```sh
python3 tools/release_gate.py \
  --root . \
  --toolbar-root ../toolbar \
  --wizard-root ../wizard \
  --bundle artifacts/extella-client-VERSION.zip
```

Local green checks are not permission to publish. Clean-account and clean-OS
matrix evidence is required from macOS Intel, macOS Apple Silicon, and Windows
11 x64. Publishing, merging to primary repositories, and enabling updates happen
only after explicit owner approval.
