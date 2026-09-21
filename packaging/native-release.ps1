# Internal build stage. Public entry point: build-release.ps1, clean HEAD only.
[CmdletBinding()]
param([string]$BuildRoot, [string]$OutputRoot, [string]$SourceCommit,
      [string]$Node, [string]$Go, [string]$Python)
$ErrorActionPreference = 'Stop'
if ($env:CLAO_RELEASE_BUILD -ne 'tracked-head-windows-x64' -or $SourceCommit -notmatch '^[0-9a-f]{40}$' -or $env:OS -ne 'Windows_NT') {
    throw 'Invoke packaging/build-release.ps1 from a clean Windows checkout.'
}
function Run([string]$Command, [string[]]$Arguments) {
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Build command failed: $Command (exit $LASTEXITCODE)" }
}
function Write-Utf8([string]$Path, [string]$Text) {
    [IO.File]::WriteAllText($Path, $Text, [Text.UTF8Encoding]::new($false))
}
$nodeExe = (Get-Command $Node -ErrorAction Stop).Source
$goExe = (Get-Command $Go -ErrorAction Stop).Source
$pythonExe = (Get-Command $Python -ErrorAction Stop).Source
$oldPath = $env:PATH
$env:PATH = (Split-Path $nodeExe) + ';' + (Split-Path $goExe) + ';' + $oldPath
$npm = (Get-Command npm.cmd -ErrorAction Stop).Source
$frontend = Join-Path $BuildRoot 'ao/frontend'
$resources = Join-Path $frontend 'resources'
$runtime = Join-Path $resources 'python'
$notices = Join-Path $resources 'third-party'
try {
    New-Item -ItemType Directory -Path $runtime, $notices -Force | Out-Null
    $archive = Join-Path $OutputRoot 'python-3.12.10-embed-amd64.zip'
    Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip' -OutFile $archive -TimeoutSec 120
    if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne '4ACBED6DD1C744B0376E3B1CF57CE906F9DC9E95E68824584C8099A63025A3C3') { throw 'Python archive SHA256 mismatch.' }
    Expand-Archive -LiteralPath $archive -DestinationPath $runtime
    Run $pythonExe @('-m', 'pip', 'install', '--disable-pip-version-check', '--only-binary=:all:', '--platform', 'win_amd64', '--python-version', '3.12', '--implementation', 'cp', '--abi', 'cp312', '--require-hashes', '--no-compile', '--target', (Join-Path $runtime 'Lib/site-packages'), '-r', (Join-Path $BuildRoot 'packaging/python-runtime.lock'))
    # Embeddable Python ignores PYTHONPATH, user site packages and registry paths.
    # Keep the core inside the install, independent of launch cwd and source tree.
    Write-Utf8 (Join-Path $runtime 'python312._pth') "python312.zip`n.`nLib/site-packages`n../clao-core/src`n"
    foreach ($file in (Get-ChildItem -LiteralPath (Join-Path $resources 'clao-core') -Recurse -File)) {
        $text = Get-Content -LiteralPath $file.FullName -Raw -Encoding UTF8
        if ($text -match '(?i)sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|[A-Z]:\\Users\\|Authorization\s*:\s*Bearer\s+[A-Za-z0-9._~-]{20,}') {
            throw ('Potential credential or developer path in bundled core: ' + $file.Name)
        }
    }
    Run (Join-Path $runtime 'python.exe') @('-B', '-c', 'import yaml,jsonschema,loopcore.ao_acceptance,loopcore.ao_legacy; print("BUNDLED_PYTHON_CORE_OK")')
    Copy-Item -LiteralPath (Join-Path $BuildRoot 'ao/LICENSE') -Destination (Join-Path $notices 'AO-LICENSE.txt')
    Copy-Item -LiteralPath (Join-Path $BuildRoot 'packaging/WINDOWS-CANDIDATE.md') -Destination (Join-Path $notices 'WINDOWS-CANDIDATE.md')
    Copy-Item -LiteralPath (Join-Path $BuildRoot 'packaging/python-runtime.lock') -Destination (Join-Path $notices 'python-runtime.lock')
    Write-Utf8 (Join-Path $notices 'SOURCE.json') (([ordered]@{product='CLAO Native';version='0.3.0-rc.1';commit=$SourceCommit;upstream='AO v0.12.12';platform='windows-x64';updates='disabled';python='3.12.10'}) | ConvertTo-Json)
    Push-Location (Join-Path $BuildRoot 'ao/packages/product-ui')
    try { Run $npm @('ci', '--no-audit', '--no-fund'); Run $npm @('run', 'build') } finally { Pop-Location }
    Push-Location $frontend
    try {
        Run $npm @('ci', '--no-audit', '--no-fund')
        # npm make owns the existing daemon/browser/ACP preparations. No publish.
        Run $npm @('run', 'premake')
        Run $nodeExe @((Join-Path $BuildRoot 'packaging/collect-licenses.mjs'), $BuildRoot, $goExe)
        Run $nodeExe @('node_modules/@electron-forge/cli/dist/electron-forge-make.js', '--platform=win32', '--arch=x64')
    } finally { Pop-Location }
    $packaged = @(Get-ChildItem -LiteralPath (Join-Path $frontend 'out') -Directory | Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'clao-native.exe') })
    if ($packaged.Count -ne 1) { throw 'Expected exactly one packaged CLAO application.' }
    $product = Join-Path $OutputRoot 'clao'
    Copy-Item -LiteralPath $packaged[0].FullName -Destination $product -Recurse
    foreach ($required in @('clao-native.exe', 'resources/app.asar', 'resources/daemon/ao.exe', 'resources/python/python.exe', 'resources/clao-core/src/loopcore/ao_acceptance.py', 'resources/third-party/SOURCE.json')) {
        if (!(Test-Path -LiteralPath (Join-Path $product $required) -PathType Leaf)) { throw "Missing packaged runtime: $required" }
    }
    Run (Join-Path $product 'resources/python/python.exe') @('-B', '-c', 'import yaml,jsonschema,loopcore.ao_acceptance,loopcore.ao_legacy; print("PACKAGED_PYTHON_CORE_OK")')
    $files = @(Get-ChildItem -LiteralPath $product -Recurse -File)
    $hashes = foreach ($file in $files) {
        $relative = $file.FullName.Substring($product.Length + 1).Replace('\', '/')
        if ($relative -match '(^|/)(\.venv|\.git|__pycache__|\.pytest_cache)(/|$)|(^|/)(state\.db|auth\.json|AGENTS\.md)$|\.db-(wal|shm)$') { throw "Forbidden product content: $relative" }
        (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant() + '  ' + $relative
    }
    Write-Utf8 (Join-Path $product 'SHA256SUMS.txt') (($hashes | Sort-Object) -join "`n")
    $zip = Join-Path $OutputRoot ("clao-0.3.0-rc.1-windows-x64-" + $SourceCommit.Substring(0,12) + '.zip')
    Compress-Archive -LiteralPath $product -DestinationPath $zip
    $installers = @(Get-ChildItem -LiteralPath (Join-Path $frontend 'out/make') -Recurse -File -Filter '*.exe')
    if ($installers.Count -ne 1) { throw 'Expected exactly one NSIS installer.' }
    $installer = Join-Path $OutputRoot ('CLAO-Native-0.3.0-rc.1-Setup-' + $SourceCommit.Substring(0,12) + '.exe')
    Copy-Item -LiteralPath $installers[0].FullName -Destination $installer
    Copy-Item -LiteralPath (Join-Path $notices 'SOURCE.json') -Destination (Join-Path $OutputRoot 'SOURCE.json')
    Copy-Item -LiteralPath (Join-Path $notices 'WINDOWS-CANDIDATE.md') -Destination (Join-Path $OutputRoot 'WINDOWS-CANDIDATE.md')
    $artifactHashes = foreach ($file in @($zip, $installer, (Join-Path $OutputRoot 'SOURCE.json'), (Join-Path $OutputRoot 'WINDOWS-CANDIDATE.md'))) {
        (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant() + '  ' + (Split-Path $file -Leaf)
    }
    Write-Utf8 (Join-Path $OutputRoot 'SHA256SUMS.txt') ($artifactHashes -join "`n")
    Write-Output "RELEASE_ZIP=$zip"
    Write-Output "RELEASE_INSTALLER=$installer"
    Write-Output 'PUBLISH=NOT_RUN'
    exit 0
} finally { $env:PATH = $oldPath }
