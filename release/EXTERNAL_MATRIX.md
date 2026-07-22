# Extella Client external release matrix

This protocol is required before a candidate can become `released`. It must be
run under a clean operating-system user and a clean Extella account on exactly:

- macOS x86_64 (Intel);
- macOS arm64 (Apple Silicon);
- Windows 11 x64.

The runner writes only categorical counts, artifact hashes, a random session
identifier, and hashed boot markers. The Extella token is entered through a
hidden prompt and is never written to the evidence file or process arguments.

Use the candidate filename, SHA-256, and byte size from
`release/release-manifest.json`. Do not substitute a rebuilt or renamed ZIP.
Keep one evidence JSON per platform and a separate evidence JSON for the
previous-release upgrade track.

## macOS Intel and Apple Silicon

Set the platform to `macos-x86_64` on Intel or `macos-arm64` on Apple Silicon:

```sh
CANDIDATE=/absolute/path/extella-client-2.0.0-rc.1.zip
MANIFEST=/absolute/path/release-manifest.json
RESULT=/absolute/path/extella-matrix-macos.json
PLATFORM=macos-arm64
SHA256=<distribution.sha256 from release-manifest.json>
BYTES=<distribution.bytes from release-manifest.json>
```

The first command proves the clean-user baseline with the bootstrap's temporary
pinned Python, then performs the real installation and prompts for the clean
account token:

```sh
sh toolbar/install-all.sh \
  --bundle "$CANDIDATE" \
  --sha256 "$SHA256" \
  --bytes "$BYTES" \
  --matrix-phase baseline \
  --matrix-result "$RESULT" \
  --release-manifest "$MANIFEST"
```

Use the installed managed Python and matrix runner for subsequent phases:

The `installed` phase first asks the protected local Activity Center to install
exactly the three release-gated on-demand programs. Each lifecycle must finish
its account smoke, owned PID health check and real HTML UI probe before the
phase prompts for the hidden token and verifies the complete client. The
`upgraded` phase repeats the same lifecycle so a previous package revision is
repaired and restarted under proven ownership.

```sh
DATA="$HOME/Library/Application Support/Extella"
PYTHON=$(find "$DATA/runtime/python" -type f -name python3.12 -perm -u+x | head -n 1)
RUNNER="$DATA/installer/external_matrix.py"

"$PYTHON" "$RUNNER" --phase installed --expected-platform "$PLATFORM" --candidate "$CANDIDATE" --release-manifest "$MANIFEST" --result "$RESULT"
"$PYTHON" "$RUNNER" --phase controlled --expected-platform "$PLATFORM" --candidate "$CANDIDATE" --release-manifest "$MANIFEST" --result "$RESULT"
```

Run the same native installer again without a matrix initial phase, then record
the idempotent reinstall:

```sh
sh toolbar/install-all.sh --bundle "$CANDIDATE" --sha256 "$SHA256" --bytes "$BYTES"
"$PYTHON" "$RUNNER" --phase reinstalled --expected-platform "$PLATFORM" --candidate "$CANDIDATE" --release-manifest "$MANIFEST" --result "$RESULT"
```

Prepare a reversible repair probe. This removes only the installer-owned
`toolbar.js`. Immediately rerun the installer and record the repaired state:

```sh
"$PYTHON" "$RUNNER" --phase repair-prepared --expected-platform "$PLATFORM" --candidate "$CANDIDATE" --release-manifest "$MANIFEST" --result "$RESULT"
sh toolbar/install-all.sh --bundle "$CANDIDATE" --sha256 "$SHA256" --bytes "$BYTES"
"$PYTHON" "$RUNNER" --phase repaired --expected-platform "$PLATFORM" --candidate "$CANDIDATE" --release-manifest "$MANIFEST" --result "$RESULT"
```

Open Extella Desktop, confirm the toolbar and the schedule/Activity Center card
are visible, open every bundled local UI from the toolbar, and capture a PNG or
JPEG screenshot. The runner stores only its hash and byte size:

```sh
"$PYTHON" "$RUNNER" --phase live-ui --expected-platform "$PLATFORM" --candidate "$CANDIDATE" --release-manifest "$MANIFEST" --result "$RESULT" --desktop-evidence /absolute/path/live-extella.png
```

Restart macOS through the normal user interface. After login, do not manually
start any Extella service. Recreate `PYTHON` and `RUNNER`, then record the cold
restart. This phase fails unless the operating-system boot marker changed:

```sh
"$PYTHON" "$RUNNER" --phase restarted --expected-platform "$PLATFORM" --candidate "$CANDIDATE" --release-manifest "$MANIFEST" --result "$RESULT"
```

Finally run the owned uninstaller through the verified native bootstrap. It
first removes the three release-gated plugin lifecycles and their account
resources, then the base account/client state. User uploads, generated
documents and declared mutable data remain preserved. Its temporary Python
lives outside Extella, so the managed runtime can also be removed completely:

```sh
sh toolbar/install-all.sh --uninstall --bundle "$CANDIDATE" --sha256 "$SHA256" --bytes "$BYTES" --release-manifest "$MANIFEST" --matrix-result "$RESULT"
```

## Windows 11 x64

Run in 64-bit PowerShell under a clean standard user:

```powershell
$Candidate = "C:\absolute\path\extella-client-2.0.0-rc.1.zip"
$Manifest = "C:\absolute\path\release-manifest.json"
$Result = "C:\absolute\path\extella-matrix-windows11.json"
$Sha256 = "<distribution.sha256 from release-manifest.json>"
$Bytes = <distribution.bytes from release-manifest.json>
$Platform = "windows11-x86_64"

& .\toolbar\install-all.ps1 `
  -BundlePath $Candidate `
  -BundleSha256 $Sha256 `
  -BundleBytes $Bytes `
  -MatrixPhase baseline `
  -MatrixResult $Result `
  -ReleaseManifest $Manifest
```

Locate the installed managed Python and run the same phases as on macOS:

```powershell
$Data = Join-Path $env:LOCALAPPDATA "Extella"
$Python = Get-ChildItem (Join-Path $Data "runtime\python") -Recurse -File -Filter python.exe |
  Where-Object { $_.FullName -notmatch '[\\/]site-packages[\\/]' } |
  Sort-Object { $_.FullName.Length } |
  Select-Object -First 1 -ExpandProperty FullName
$Runner = Join-Path $Data "installer\external_matrix.py"

& $Python $Runner --phase installed --expected-platform $Platform --candidate $Candidate --release-manifest $Manifest --result $Result
& $Python $Runner --phase controlled --expected-platform $Platform --candidate $Candidate --release-manifest $Manifest --result $Result

& .\toolbar\install-all.ps1 -BundlePath $Candidate -BundleSha256 $Sha256 -BundleBytes $Bytes
& $Python $Runner --phase reinstalled --expected-platform $Platform --candidate $Candidate --release-manifest $Manifest --result $Result

& $Python $Runner --phase repair-prepared --expected-platform $Platform --candidate $Candidate --release-manifest $Manifest --result $Result
& .\toolbar\install-all.ps1 -BundlePath $Candidate -BundleSha256 $Sha256 -BundleBytes $Bytes
& $Python $Runner --phase repaired --expected-platform $Platform --candidate $Candidate --release-manifest $Manifest --result $Result

& $Python $Runner --phase live-ui --expected-platform $Platform --candidate $Candidate --release-manifest $Manifest --result $Result --desktop-evidence C:\absolute\path\live-extella.png
```

Restart Windows 11 normally. After login, do not manually start Extella
services. Recreate `$Python` and `$Runner`, record `restarted`, then uninstall
through the temporary verified bootstrap Python. This avoids a locked running
`python.exe` inside the managed runtime:

```powershell
& $Python $Runner --phase restarted --expected-platform $Platform --candidate $Candidate --release-manifest $Manifest --result $Result
& .\toolbar\install-all.ps1 -Uninstall -BundlePath $Candidate -BundleSha256 $Sha256 -BundleBytes $Bytes -ReleaseManifest $Manifest -MatrixResult $Result
```

## Previous-release upgrade track

Use a separate clean user with the supported previous Extella release already
installed. Pass `previous-release` instead of `baseline` to the new candidate's
native bootstrap and use a separate result file. The bootstrap records the old
version before any candidate mutation and then upgrades it. After installation:

```text
external_matrix.py --phase upgraded --expected-platform <platform> --candidate <candidate> --release-manifest <manifest> --result <upgrade-result>
```

The phase fails unless both local and account transaction chains retain a
different previous release version. Continue with `controlled`, `live-ui`,
`restarted`, and the matrix-aware uninstall.

## Acceptance

A result is admissible only when its candidate hash, size, file count, source
SHAs, and platform match the release manifest; all required phases are
`passed`; the cold-restart phase has a new boot marker; and the live UI
screenshot hash has been reviewed. A failed phase remains evidence of failure
and must not be edited to `passed`; start a new clean-user run after fixing and
rebuilding the candidate.
