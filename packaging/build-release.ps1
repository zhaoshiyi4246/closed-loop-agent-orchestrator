[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$OutputDirectory
)

$ErrorActionPreference = "Stop"

function Invoke-Git {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    $output = & $script:GitCommand @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "git command failed: git $($Arguments -join ' ')"
    }
    return @($output)
}

function Get-RelativeProductPath {
    param([string]$Root, [string]$Path)
    $rootUri = [uri]($Root.TrimEnd("\") + "\")
    $pathUri = [uri]$Path
    return [uri]::UnescapeDataString(
        $rootUri.MakeRelativeUri($pathUri).ToString()).Replace("\", "/")
}

function Assert-RelativePosixPath {
    param([string]$Path, [string]$Label)
    if ([string]::IsNullOrWhiteSpace($Path)) {
        throw "$Label path is empty."
    }
    $segments = @($Path.Split(
        "/", [StringSplitOptions]::RemoveEmptyEntries))
    if ($Path -match '^[A-Za-z]:' -or $Path.StartsWith("/") -or
            $Path.StartsWith("\") -or $Path.Contains("\") -or
            $Path.Contains("//") -or $segments.Count -eq 0 -or
            $segments -contains "." -or $segments -contains "..") {
        throw "Illegal $Label path: $Path"
    }
}

try {
    $script:GitCommand = (Get-Command "git" -ErrorAction SilentlyContinue).Source
    if (-not $script:GitCommand) {
        throw "Git executable was not found on PATH."
    }

    $repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
    $inside = Invoke-Git -Arguments @("-C", $repoRoot, "rev-parse",
                                      "--is-inside-work-tree")
    if (($inside -join "").Trim().ToLowerInvariant() -ne "true") {
        throw "build-release.ps1 is not inside a Git repository."
    }
    $dirty = Invoke-Git -Arguments @("-C", $repoRoot, "status",
                                     "--porcelain", "--untracked-files=all")
    if (@($dirty).Count -ne 0) {
        throw "Git working tree is not clean; commit or remove changes first."
    }

    $manifestPath = Join-Path $PSScriptRoot "release-manifest.txt"
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        throw "Release manifest is missing."
    }
    $entries = @(
        Get-Content -LiteralPath $manifestPath -Encoding UTF8 |
            ForEach-Object { $_.Trim() } |
            Where-Object { $_ -and -not $_.StartsWith("#") }
    )
    if ($entries.Count -eq 0) {
        throw "Release manifest has no mappings."
    }

    $mappings = [Collections.Generic.List[object]]::new()
    $seenMappings = [Collections.Generic.HashSet[string]]::new(
        [StringComparer]::Ordinal)
    foreach ($entry in $entries) {
        if ([regex]::Matches($entry, '=>').Count -ne 1) {
            throw "Release manifest mapping must contain exactly one =>: $entry"
        }
        $delimiter = $entry.IndexOf("=>", [StringComparison]::Ordinal)
        $source = $entry.Substring(0, $delimiter).Trim()
        $destination = $entry.Substring($delimiter + 2).Trim()
        Assert-RelativePosixPath -Path $source -Label "source"
        Assert-RelativePosixPath -Path $destination -Label "destination"
        $isPrefix = $source.EndsWith("/")
        if ($isPrefix -ne $destination.EndsWith("/")) {
            throw "Source and destination must both be prefix paths or exact files: $entry"
        }
        if ($destination.TrimEnd("/") -ieq "SHA256SUMS.txt") {
            throw "SHA256SUMS.txt is a reserved generated destination."
        }
        $mappingKey = $source + [char]0 + $destination
        if (-not $seenMappings.Add($mappingKey)) {
            throw "Duplicate release manifest mapping: $entry"
        }
        $mappings.Add([pscustomobject]@{
            Source = $source
            Destination = $destination
            IsPrefix = $isPrefix
        })
    }

    $commitOutput = Invoke-Git -Arguments @("-C", $repoRoot, "rev-parse",
                                             "HEAD")
    $commit = ($commitOutput -join "").Trim()
    if ($commit -notmatch '^[0-9a-f]{40}$') {
        throw "Could not resolve the source commit."
    }
    [string[]]$tracked = @(Invoke-Git -Arguments @(
        "-c", "core.quotepath=false", "-C", $repoRoot, "ls-tree", "-r",
        "--name-only", $commit))
    $trackedSet = [Collections.Generic.HashSet[string]]::new(
        [StringComparer]::Ordinal)
    foreach ($path in $tracked) {
        [void]$trackedSet.Add($path)
    }

    $fileMappings = [Collections.Generic.List[object]]::new()
    $sourceSet = [Collections.Generic.HashSet[string]]::new(
        [StringComparer]::Ordinal)
    $destinationSet = [Collections.Generic.HashSet[string]]::new(
        [StringComparer]::OrdinalIgnoreCase)
    foreach ($mapping in $mappings) {
        if ($mapping.IsPrefix) {
            $matches = @($tracked | Where-Object {
                $_.StartsWith($mapping.Source, [StringComparison]::Ordinal)
            })
            if ($matches.Count -eq 0) {
                throw "Manifest source prefix has no tracked files at HEAD: $($mapping.Source)"
            }
            foreach ($sourcePath in $matches) {
                $suffix = $sourcePath.Substring($mapping.Source.Length)
                $destinationPath = $mapping.Destination + $suffix
                if (-not $destinationSet.Add($destinationPath)) {
                    throw "Release destination collision: $destinationPath"
                }
                [void]$sourceSet.Add($sourcePath)
                $fileMappings.Add([pscustomobject]@{
                    Source = $sourcePath
                    Destination = $destinationPath
                })
            }
        }
        else {
            if (-not $trackedSet.Contains($mapping.Source)) {
                throw "Manifest source file is not tracked at HEAD: $($mapping.Source)"
            }
            if (-not $destinationSet.Add($mapping.Destination)) {
                throw "Release destination collision: $($mapping.Destination)"
            }
            [void]$sourceSet.Add($mapping.Source)
            $fileMappings.Add([pscustomobject]@{
                Source = $mapping.Source
                Destination = $mapping.Destination
            })
        }
    }

    [string[]]$expectedSources = @($sourceSet)
    [Array]::Sort($expectedSources, [StringComparer]::Ordinal)
    [string[]]$expectedDestinations = @(
        $fileMappings | ForEach-Object { $_.Destination })
    [Array]::Sort($expectedDestinations, [StringComparer]::Ordinal)

    $outputRoot = [IO.Path]::GetFullPath($OutputDirectory)
    $repoPrefix = $repoRoot.TrimEnd("\") + "\"
    if ($outputRoot.Equals($repoRoot, [StringComparison]::OrdinalIgnoreCase) -or
            $outputRoot.StartsWith($repoPrefix,
                [StringComparison]::OrdinalIgnoreCase)) {
        throw "OutputDirectory must be outside the source repository."
    }
    if (Test-Path -LiteralPath $outputRoot) {
        throw "OutputDirectory already exists; choose a new empty path."
    }
    New-Item -ItemType Directory -Path $outputRoot | Out-Null
    $sourceStage = Join-Path $outputRoot "source-stage"
    $sourceArchive = Join-Path $outputRoot "source-from-head.zip"
    $productRoot = Join-Path $outputRoot "clao"

    $archiveArgs = @("-C", $repoRoot, "archive", "--format=zip",
                     "--output=$sourceArchive", $commit, "--") + $expectedSources
    & $script:GitCommand @archiveArgs
    if ($LASTEXITCODE -ne 0 -or
            -not (Test-Path -LiteralPath $sourceArchive -PathType Leaf)) {
        throw "git archive failed."
    }
    Expand-Archive -LiteralPath $sourceArchive -DestinationPath $sourceStage
    Remove-Item -LiteralPath $sourceArchive -Force

    [string[]]$stagedSources = @(
        Get-ChildItem -LiteralPath $sourceStage -Recurse -File |
            ForEach-Object {
                Get-RelativeProductPath $sourceStage $_.FullName
            }
    )
    [Array]::Sort($stagedSources, [StringComparer]::Ordinal)
    $sourceDifference = Compare-Object -ReferenceObject $expectedSources -DifferenceObject $stagedSources -CaseSensitive
    if ($stagedSources.Count -ne $expectedSources.Count -or $sourceDifference) {
        throw "HEAD source stage does not match manifest source expansion."
    }

    foreach ($mapping in $fileMappings) {
        $sourceFile = Join-Path $sourceStage $mapping.Source.Replace("/", "\")
        $destinationFile = Join-Path $productRoot $mapping.Destination.Replace("/", "\")
        $destinationParent = Split-Path -Parent $destinationFile
        if (-not (Test-Path -LiteralPath $destinationParent)) {
            New-Item -ItemType Directory -Path $destinationParent -Force |
                Out-Null
        }
        Copy-Item -LiteralPath $sourceFile -Destination $destinationFile
    }

    [string[]]$staged = @(
        Get-ChildItem -LiteralPath $productRoot -Recurse -File |
            ForEach-Object {
                Get-RelativeProductPath $productRoot $_.FullName
            }
    )
    [Array]::Sort($staged, [StringComparer]::Ordinal)
    $productDifference = Compare-Object -ReferenceObject $expectedDestinations -DifferenceObject $staged -CaseSensitive
    if ($staged.Count -ne $expectedDestinations.Count -or $productDifference) {
        throw "Product file set does not match the manifest mapping."
    }
    Remove-Item -LiteralPath $sourceStage -Recurse -Force

    $forbiddenNames = @(
        ".venv", "runtime", "__pycache__", ".pytest_cache", "clao-src",
        "ao-supervision-sidecar", "closed-loop-demo",
        "closed-loop-demo-origin.git", "交付", "closed-loop-v2", "release")
    $forbiddenFiles = @(
        "PLANS.md", "AGENTS.md", "PROJECT.md", "README-交付说明.md",
        "ARCHITECTURE-v0.2.md")
    foreach ($relative in $staged) {
        $segments = $relative.Split("/")
        $leaf = $segments[-1]
        if (@($segments | Where-Object {
                    $_ -in $forbiddenNames
                }).Count -gt 0 -or $leaf -in $forbiddenFiles -or
                $leaf -like "*.pyc" -or $leaf -like "*.db-wal" -or
                $leaf -like "*.db-shm" -or $leaf -eq "state.db" -or
                $leaf -eq "bus_traffic.jsonl" -or
                $leaf -like "mission-panel-*.json" -or
                $leaf -like "codex-last-message*" -or
                $leaf -like "*.log") {
            throw "Generated, development, or historical content reached product: $relative"
        }
    }

    $missingLinks = @()
    foreach ($markdown in (
            Get-ChildItem -LiteralPath $productRoot -Recurse -File -Filter "*.md")) {
        $text = Get-Content -LiteralPath $markdown.FullName -Raw -Encoding UTF8
        foreach ($match in [regex]::Matches(
                $text, '\[[^\]]+\]\(([^)]+)\)')) {
            $target = $match.Groups[1].Value.Split("#")[0]
            if (-not $target -or $target -match '^(https?://|mailto:)') {
                continue
            }
            $candidate = Join-Path $markdown.DirectoryName ([uri]::UnescapeDataString($target))
            if (-not (Test-Path -LiteralPath $candidate)) {
                $missingLinks += (
                    Get-RelativeProductPath $productRoot $markdown.FullName)
            }
        }
    }
    if ($missingLinks.Count -ne 0) {
        throw "Product Markdown contains missing local links."
    }

    $secretPatterns = @(
        '(?i)[A-Z]:\\Users\\',
        '(?i)E:\\桌面\\',
        '(?i)sk-[A-Za-z0-9_-]{20,}',
        '(?i)gh[pousr]_[A-Za-z0-9]{20,}',
        '(?i)Authorization\s*:\s*Bearer\s+[A-Za-z0-9._~-]{20,}',
        '(?i)(OPENAI_API_KEY|ANTHROPIC_API_KEY)\s*[:=]\s*["'']?[A-Za-z0-9_-]{16,}'
    )
    foreach ($relative in $staged) {
        $file = Join-Path $productRoot $relative.Replace("/", "\")
        try {
            $text = Get-Content -LiteralPath $file -Raw -Encoding UTF8
        }
        catch {
            continue
        }
        foreach ($pattern in $secretPatterns) {
            if ($text -match $pattern) {
                throw "Potential credential or developer path in product: $relative"
            }
        }
    }

    $hashLines = [Collections.Generic.List[string]]::new()
    foreach ($relative in $staged) {
        $file = Join-Path $productRoot $relative.Replace("/", "\")
        $hash = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash
        $hashLines.Add($hash.ToLowerInvariant() + "  " + $relative)
    }
    $hashFile = Join-Path $productRoot "SHA256SUMS.txt"
    [IO.File]::WriteAllLines(
        $hashFile, $hashLines, [Text.UTF8Encoding]::new($false))
    if (-not (Test-Path -LiteralPath $hashFile -PathType Leaf)) {
        throw "Failed to generate SHA256SUMS.txt."
    }

    $zipName = "clao-v0.2-$($commit.Substring(0, 12)).zip"
    $zipPath = Join-Path $outputRoot $zipName
    Compress-Archive -LiteralPath $productRoot -DestinationPath $zipPath
    if (-not (Test-Path -LiteralPath $zipPath -PathType Leaf)) {
        throw "Failed to generate the release zip."
    }

    Write-Output "SOURCE_COMMIT=$commit"
    Write-Output "MANIFEST_FILES=$($expectedDestinations.Count)"
    Write-Output "PRODUCT_ROOT=clao"
    Write-Output "MARKDOWN_MISSING=0"
    Write-Output "SECRET_FINDINGS=0"
    Write-Output "SHA256SUMS=clao/SHA256SUMS.txt"
    Write-Output "RELEASE_ZIP=$zipName"
    exit 0
}
catch {
    Write-Error ("Release build failed: " + $_.Exception.Message)
    exit 1
}
