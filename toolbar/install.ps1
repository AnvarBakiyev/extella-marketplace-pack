# Compatibility wrapper for the versioned, hash-verified Windows 11 bootstrap.
[CmdletBinding()]
param(
    [string]$BundlePath = $env:EXTELLA_BUNDLE_PATH,
    [string]$BundleUrl = $env:EXTELLA_BUNDLE_URL,
    [string]$BundleSha256 = $env:EXTELLA_BUNDLE_SHA256,
    [long]$BundleBytes = $(if ($env:EXTELLA_BUNDLE_BYTES) { [long]$env:EXTELLA_BUNDLE_BYTES } else { 0 }),
    [switch]$NoStart,
    [switch]$VerifyOnly,
    [switch]$Uninstall,
    [ValidateSet("baseline", "previous-release")]
    [string]$MatrixPhase,
    [string]$MatrixResult,
    [string]$ReleaseManifest
)

& (Join-Path $PSScriptRoot "install-all.ps1") @PSBoundParameters
exit $LASTEXITCODE
