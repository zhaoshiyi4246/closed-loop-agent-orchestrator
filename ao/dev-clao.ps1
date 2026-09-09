param(
    [string]$Node = 'node',
    [string]$Go = 'go',
    [string]$Python = (Join-Path $PSScriptRoot '../clao/.venv/Scripts/python.exe'),
    [string]$DataHome = (Join-Path $env:USERPROFILE '.clao-ao'),
    [int]$Port = 7312,
    [switch]$SkipBuild
)
$ErrorActionPreference = 'Stop'
if ($Port -lt 1024 -or $Port -gt 65535) { throw 'Port must be between 1024 and 65535.' }
$nativeHome = [IO.Path]::GetFullPath($DataHome)
$officialHome = [IO.Path]::GetFullPath((Join-Path $env:USERPROFILE '.ao'))
if ($nativeHome -eq $officialHome -or $nativeHome.StartsWith($officialHome + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Use a separate CLAO data directory, outside official AO data.'
}
$nodeExe = (Get-Command $Node -ErrorAction Stop).Source
$pythonExe = (Get-Command $Python -ErrorAction Stop).Source
$frontend = Join-Path $PSScriptRoot 'frontend'
if (!(Test-Path -LiteralPath (Join-Path $frontend 'node_modules/@electron-forge/cli/dist/electron-forge.js'))) {
    throw 'Frontend dependencies are missing. Follow ao/CLAO.md; this launcher does not install tools.'
}
$env:PATH = (Split-Path $nodeExe) + ';' + (Split-Path $pythonExe) + ';' + $env:PATH
$env:CLAO_NATIVE_HOME = $nativeHome
$env:CLAO_NATIVE_PORT = "$Port"
$env:CLAO_CORE_PYTHON = $pythonExe
$env:CLAO_CORE_ROOT = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../clao'))
# Never inherit a shell command pointing at another AO installation.
Remove-Item Env:AO_DAEMON_COMMAND -ErrorAction SilentlyContinue
$env:AO_DEV_DAEMON_BINARY = Join-Path $frontend 'daemon/ao.exe'
if (!$SkipBuild) {
    $goExe = (Get-Command $Go -ErrorAction Stop).Source
    $env:GOWORK = 'off'
    $env:GOTOOLCHAIN = 'local'
    Push-Location (Join-Path $PSScriptRoot 'backend')
    try {
        & $goExe build -o $env:AO_DEV_DAEMON_BINARY ./cmd/ao
        if ($LASTEXITCODE -ne 0) { throw 'Native daemon development build failed.' }
    } finally { Pop-Location }
}
if (!(Test-Path -LiteralPath $env:AO_DEV_DAEMON_BINARY)) { throw 'Build the derived daemon first.' }
Push-Location $frontend
try {
    & $nodeExe node_modules/@electron-forge/cli/dist/electron-forge.js start
    if ($LASTEXITCODE -ne 0) { throw 'Native desktop startup failed.' }
} finally { Pop-Location }
