param(
    [string]$Node = '',
    [string]$Go = '',
    [string]$Python = '',
    [string]$DataHome = (Join-Path $env:USERPROFILE '.clao-ao'),
    [int]$Port = 7312,
    [switch]$SkipBuild,
    [switch]$IsolatedAccount
)
$ErrorActionPreference = 'Stop'
if ($Port -lt 1024 -or $Port -gt 65535) { throw 'Port must be between 1024 and 65535.' }
$nativeHome = [IO.Path]::GetFullPath($DataHome)
$officialHome = [IO.Path]::GetFullPath((Join-Path $env:USERPROFILE '.ao'))
if ($nativeHome -eq $officialHome -or $nativeHome.StartsWith($officialHome + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Use a separate CLAO data directory, outside official AO data.'
}
function Resolve-ExistingTool([string]$Explicit, [string]$Name, [string[]]$Candidates) {
    if ($Explicit) { return (Get-Command $Explicit -ErrorAction Stop).Source }
    $available = Get-Command $Name -ErrorAction SilentlyContinue
    if ($available) { return $available.Source }
    foreach ($candidate in $Candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) { return [IO.Path]::GetFullPath($candidate) }
    }
    throw "$Name is not installed or could not be found. Pass its existing executable path; this launcher does not install tools."
}
$nodeExe = Resolve-ExistingTool $Node 'node' @((Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'))
$pythonCandidates = @((Join-Path $PSScriptRoot '../clao/.venv/Scripts/python.exe'), (Join-Path $PSScriptRoot '../../closed-loop-agent-orchestrator/clao/.venv/Scripts/python.exe'))
$pythonExe = Resolve-ExistingTool $Python '__clao_venv_python__' $pythonCandidates
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
    $goCandidates = @(Get-ChildItem -LiteralPath (Join-Path $env:USERPROFILE 'go/pkg/mod/golang.org') -Directory -ErrorAction SilentlyContinue | Where-Object Name -Like 'toolchain@*.windows-amd64' | Sort-Object Name -Descending | ForEach-Object { Join-Path $_.FullName 'bin/go.exe' })
    $goExe = Resolve-ExistingTool $Go 'go' $goCandidates
    $env:PATH = (Split-Path $goExe) + ';' + $env:PATH
    $env:GOWORK = 'off'
    $env:GOTOOLCHAIN = 'local'
    Push-Location (Join-Path $PSScriptRoot 'backend')
    try {
        & $goExe build -o $env:AO_DEV_DAEMON_BINARY ./cmd/ao
        if ($LASTEXITCODE -ne 0) { throw 'Native daemon development build failed.' }
    } finally { Pop-Location }
}
if (!(Test-Path -LiteralPath $env:AO_DEV_DAEMON_BINARY)) { throw 'Build the derived daemon first.' }
if ($IsolatedAccount) {
    # Empty-account developer checks are opt-in. Build before changing the
    # process profile so Go uses the existing dependency cache.
    $accountHome = Join-Path $nativeHome 'empty-account-profile'
    foreach ($directory in @($accountHome, (Join-Path $accountHome 'appdata'), (Join-Path $accountHome 'local'), (Join-Path $accountHome 'config'), (Join-Path $accountHome 'share'), (Join-Path $accountHome '.codex'))) {
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
    }
    $env:USERPROFILE = $accountHome
    $env:HOME = $accountHome
    $env:APPDATA = Join-Path $accountHome 'appdata'
    $env:LOCALAPPDATA = Join-Path $accountHome 'local'
    $env:XDG_CONFIG_HOME = Join-Path $accountHome 'config'
    $env:XDG_DATA_HOME = Join-Path $accountHome 'share'
    $env:CODEX_HOME = Join-Path $accountHome '.codex'
    Write-Host 'CLAO developer check: empty account profile; no existing login has been imported.'
} else {
    Write-Host 'CLAO manual use: independent application data; native tools retain their own account selection.'
}
Write-Host "CLAO data: $nativeHome | loopback port: $Port"
Push-Location $frontend
try {
    # The installed Forge start entry uses the existing dependencies directly;
    # it does not need a separately installed npm to report its version.
    & $nodeExe node_modules/@electron-forge/cli/dist/electron-forge-start.js
    if ($LASTEXITCODE -ne 0) { throw 'Native desktop startup failed.' }
} finally { Pop-Location }
