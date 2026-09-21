[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$OutputDirectory,
    [string]$Node = "node",
    [string]$Go = "go",
    [string]$Python = "python"
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
    $commit = ((Invoke-Git -Arguments @('-C', $repoRoot, 'rev-parse', 'HEAD')) -join '').Trim()
    if ($commit -notmatch '^[0-9a-f]{40}$') { throw 'Could not resolve the source commit.' }
    $entries = @(
        Invoke-Git -Arguments @('-C', $repoRoot, 'show', ($commit + ':packaging/release-manifest.txt')) |
            ForEach-Object { $_.Trim() } |
            Where-Object { $_ -and -not $_.StartsWith("#") }
    )
    if ($entries.Count -eq 0) {
        throw "Release manifest has no mappings."
    }

    $mappings = [Collections.Generic.List[object]]::new()
    $runtimeResources = [Collections.Generic.List[string]]::new()
    $seenMappings = [Collections.Generic.HashSet[string]]::new(
        [StringComparer]::Ordinal)
    foreach ($entry in $entries) {
        if ($entry.StartsWith('@resource ')) {
            $resource = $entry.Substring(10).Trim()
            Assert-RelativePosixPath -Path $resource -Label 'runtime resource'
            if ($runtimeResources.Contains($resource)) { throw "Duplicate runtime resource: $resource" }
            $runtimeResources.Add($resource)
            continue
        }
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
    # Reject junction/symlink ancestors before creating or recursively removing
    # anything below the requested outside output directory.
    $ancestor = Split-Path -Parent $outputRoot
    while ($ancestor) {
        if ((Test-Path -LiteralPath $ancestor) -and ((Get-Item -LiteralPath $ancestor).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw 'OutputDirectory must not traverse a junction or symbolic link.'
        }
        $ancestor = Split-Path -Parent $ancestor
    }
    New-Item -ItemType Directory -Path $outputRoot | Out-Null
    $sourceStage = Join-Path $outputRoot "source-stage"
    $sourceArchive = Join-Path $outputRoot "source-from-head.zip"
    $productRoot = Join-Path $outputRoot "build-root"

    # Use the bounded manifest pathspecs, not thousands of expanded filenames
    # (the native source tree exceeds Windows' process command-line limit).
    $archiveArgs = @("-C", $repoRoot, "archive", "--format=zip",
                     "--output=$sourceArchive", $commit, "--") + @($mappings | ForEach-Object { $_.Source.TrimEnd('/') })
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
    if (-not ([IO.Path]::GetFullPath($sourceStage).StartsWith($outputRoot.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase))) { throw 'Source stage escaped output directory.' }
    Remove-Item -LiteralPath $sourceStage -Recurse -Force

    # Build only the committed helper extracted by this manifest. Build tools and
    # source files remain in build-root and never enter the distributable clao/.
    $env:CLAO_RELEASE_BUILD = "tracked-head-windows-x64"
    if ($runtimeResources.Count -eq 0) { throw 'Manifest does not declare runtime resources.' }
    $env:CLAO_RELEASE_RESOURCES = ConvertTo-Json -InputObject @($runtimeResources) -Compress
    & (Join-Path $productRoot "packaging/native-release.ps1") -BuildRoot $productRoot -OutputRoot $outputRoot -SourceCommit $commit -Node $Node -Go $Go -Python $Python
    if ($LASTEXITCODE -ne 0) { throw "Native candidate build failed." }
    Write-Output "SOURCE_COMMIT=$commit"
    Write-Output "MANIFEST_FILES=$($expectedDestinations.Count)"
    exit 0
}
catch {
    Write-Error ("Release build failed: " + $_.Exception.Message)
    exit 1
}
finally {
    Remove-Item Env:CLAO_RELEASE_BUILD -ErrorAction SilentlyContinue
    Remove-Item Env:CLAO_RELEASE_RESOURCES -ErrorAction SilentlyContinue
}
