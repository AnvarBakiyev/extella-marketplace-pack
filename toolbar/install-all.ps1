# Native fail-closed bootstrap for Extella Client on Windows 11 x64.
[CmdletBinding()]
param(
    [string]$BundlePath = $env:EXTELLA_BUNDLE_PATH,
    [string]$BundleUrl = $env:EXTELLA_BUNDLE_URL,
    [string]$BundleSha256 = $env:EXTELLA_BUNDLE_SHA256,
    [long]$BundleBytes = $(if ($env:EXTELLA_BUNDLE_BYTES) { [long]$env:EXTELLA_BUNDLE_BYTES } else { 0 }),
    [switch]$NoStart,
    [switch]$VerifyOnly
)

$ErrorActionPreference = "Stop"
$PythonVersion = "3.12.13"
$UvVersion = "0.11.30"
$UvArchive = "uv-x86_64-pc-windows-msvc.zip"
$UvBytes = 25710044
$UvSha256 = "be8d78c992312212e5cc05e9f9de3fa996db73b7c86a186dfb9231eb9f91d33e"

function Stop-Unsupported([string]$Message) {
    [Console]::Error.WriteLine("$Message No changes were made.")
    exit 3
}

# Keep platform rejection before temp directories, downloads, and all mutation.
if (-not $IsWindows -and [Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    Stop-Unsupported "Extella Client supports Windows 11 x64 only in this bootstrap."
}
$Architecture = [Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()
if ($Architecture -ne "X64") {
    Stop-Unsupported "Unsupported Windows architecture: $Architecture. Required: x64."
}
try {
    $Build = [Environment]::OSVersion.Version.Build
    if ($Build -lt 22000) {
        Stop-Unsupported "Unsupported Windows build $Build. Windows 11 build 22000 or newer is required."
    }
} catch {
    Stop-Unsupported "Could not verify the Windows 11 build."
}

if (($BundlePath -and $BundleUrl) -or (-not $BundlePath -and -not $BundleUrl)) {
    throw "Specify exactly one of -BundlePath or -BundleUrl. Raw main branches are intentionally unsupported."
}
if ($BundleUrl -and -not $BundleUrl.StartsWith("https://", [StringComparison]::OrdinalIgnoreCase)) {
    throw "Bundle URL must use HTTPS."
}
if ($BundleSha256 -notmatch '^[0-9a-fA-F]{64}$') {
    throw "A 64-character bundle SHA-256 is required."
}
if ($BundleBytes -le 0) {
    throw "A positive bundle byte size is required."
}

$Work = Join-Path ([IO.Path]::GetTempPath()) ("extella-client-" + [guid]::NewGuid().ToString("N"))
$Bundle = Join-Path $Work "extella-client.zip"
try {
    New-Item -ItemType Directory -Path $Work | Out-Null
    if ($BundlePath) {
        $ResolvedBundle = (Resolve-Path -LiteralPath $BundlePath).Path
        Copy-Item -LiteralPath $ResolvedBundle -Destination $Bundle
    } else {
        Invoke-WebRequest -Uri $BundleUrl -OutFile $Bundle -UseBasicParsing
    }
    $ActualBytes = (Get-Item -LiteralPath $Bundle).Length
    if ($ActualBytes -ne $BundleBytes) {
        throw "Bundle size mismatch: expected $BundleBytes, got $ActualBytes."
    }
    $ActualSha = (Get-FileHash -LiteralPath $Bundle -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($ActualSha -ne $BundleSha256.ToLowerInvariant()) {
        throw "Bundle SHA-256 mismatch. No Extella files were changed."
    }

    $UvUrl = "https://github.com/astral-sh/uv/releases/download/$UvVersion/$UvArchive"
    $UvPackage = Join-Path $Work $UvArchive
    Invoke-WebRequest -Uri $UvUrl -OutFile $UvPackage -UseBasicParsing
    if ((Get-Item -LiteralPath $UvPackage).Length -ne $UvBytes) {
        throw "uv archive size mismatch."
    }
    if ((Get-FileHash -LiteralPath $UvPackage -Algorithm SHA256).Hash.ToLowerInvariant() -ne $UvSha256) {
        throw "uv archive SHA-256 mismatch."
    }
    $UvRoot = Join-Path $Work "uv"
    Expand-Archive -LiteralPath $UvPackage -DestinationPath $UvRoot
    $Uv = Get-ChildItem -LiteralPath $UvRoot -Recurse -File -Filter "uv.exe" | Select-Object -First 1
    if (-not $Uv) { throw "Verified uv archive did not contain uv.exe." }

    $PythonRoot = Join-Path $Work "python"
    & $Uv.FullName python install $PythonVersion --install-dir $PythonRoot --no-bin --no-registry
    if ($LASTEXITCODE -ne 0) { throw "uv could not install managed Python $PythonVersion." }
    $Python = Get-ChildItem -LiteralPath $PythonRoot -Recurse -File -Filter "python.exe" |
        Where-Object { $_.FullName -notmatch '[\\/]site-packages[\\/]' } |
        Sort-Object { $_.FullName.Length } |
        Select-Object -First 1
    if (-not $Python) { throw "Managed Python executable is missing." }
    & $Python.FullName -c "import sys; raise SystemExit(0 if sys.version_info[:3] == (3, 12, 13) else 2)"
    if ($LASTEXITCODE -ne 0) { throw "Managed Python version verification failed." }

    $Extracted = Join-Path $Work "bundle"
    New-Item -ItemType Directory -Path $Extracted | Out-Null
    $Extractor = Join-Path $Work "safe_extract.py"
    @'
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
'@ | Set-Content -LiteralPath $Extractor -Encoding UTF8
    & $Python.FullName $Extractor $Bundle $Extracted
    if ($LASTEXITCODE -ne 0) { throw "Safe bundle extraction failed." }

    $Installer = Join-Path $Extracted "payload\marketplace\installer\client_install.py"
    if (-not (Test-Path -LiteralPath $Installer -PathType Leaf)) {
        throw "Verified bundle has no client installer."
    }
    if ($VerifyOnly) {
        $PreviousPythonPath = $env:PYTHONPATH
        try {
            $env:PYTHONPATH = Join-Path $Extracted "payload\marketplace"
            & $Python.FullName -c "from pathlib import Path; from installer.bundle import verify_bundle; import sys; print(verify_bundle(Path(sys.argv[1])))" $Extracted
            if ($LASTEXITCODE -ne 0) { throw "Strict bundle verification failed." }
        } finally {
            $env:PYTHONPATH = $PreviousPythonPath
        }
        Write-Host "Verified Extella bootstrap, managed Python, and bundle for windows11-x86_64. No client files were changed."
        exit 0
    }
    $Arguments = @($Installer, "--bundle-root", $Extracted, "--bootstrap-python-root", $PythonRoot)
    if ($NoStart) { $Arguments += "--no-start" }
    Write-Host "Installing verified Extella Client bundle on windows11-x86_64..."
    & $Python.FullName @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Extella Client installer failed with exit code $LASTEXITCODE." }
} finally {
    if (Test-Path -LiteralPath $Work) {
        Remove-Item -LiteralPath $Work -Recurse -Force -ErrorAction SilentlyContinue
    }
}
