# Source preparation only. Does not install dependencies, download weights or generate.
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$workspaceRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$sourceRoot = [System.IO.Path]::GetFullPath((Join-Path $workspaceRoot '.tools/models'))
$revisions = Get-Content -LiteralPath (Join-Path $workspaceRoot 'docs/evidence/M1/candidate-revisions.json') -Raw | ConvertFrom-Json
$allowedRepositories = @('RVC-Boss/GPT-SoVITS', 'OpenTalker/SadTalker', 'TMElyralab/MuseTalk')
New-Item -ItemType Directory -Path $sourceRoot -Force | Out-Null
$results = @()
foreach ($entry in $revisions) {
    if ($entry.repository -notin $allowedRepositories -or $entry.code_revision -notmatch '^[a-f0-9]{40}$') { throw 'Unknown repository or invalid pinned revision' }
    $name = ($entry.repository -split '/')[1]
    $repoPath = [System.IO.Path]::GetFullPath((Join-Path $sourceRoot $name))
    if (-not $repoPath.StartsWith($sourceRoot + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) { throw 'Source target escapes workspace' }
    if (-not (Test-Path -LiteralPath $repoPath)) {
        & git init --quiet $repoPath
        if ($LASTEXITCODE -ne 0) { throw "git init failed for $name" }
        & git -C $repoPath remote add origin "https://github.com/$($entry.repository).git"
        if ($LASTEXITCODE -ne 0) { throw "git remote failed for $name" }
    }
    $existingHead = & git -C $repoPath rev-parse --verify HEAD 2>$null
    if ($LASTEXITCODE -eq 0 -and $existingHead -ne $entry.code_revision) { throw "Existing checkout differs from pin for $name; leave it untouched" }
    if ($LASTEXITCODE -ne 0) {
        & git -C $repoPath fetch --depth 1 origin $entry.code_revision
        if ($LASTEXITCODE -ne 0) { throw "Pinned fetch failed for $name; partial source retained" }
        & git -C $repoPath checkout --quiet --detach FETCH_HEAD
        if ($LASTEXITCODE -ne 0) { throw "Pinned checkout failed for $name" }
    }
    $actual = & git -C $repoPath rev-parse HEAD
    if ($actual -ne $entry.code_revision) { throw "Revision mismatch for $name" }
    $results += [pscustomobject]@{repository=$entry.repository; path=$repoPath; actual_code_revision=$actual;
        installed_model_environment=$false; weights_downloaded=$false; generation_called=$false}
    Write-Output "Pinned source prepared: $name"
}
$report = [pscustomobject]@{schema_version='m1.source-preparation.v1'; scope='source-only'; repositories=$results}
$report | ConvertTo-Json -Depth 6 | Set-Content -Encoding utf8 (Join-Path $workspaceRoot 'docs/evidence/M1/local-model-sources.json')
