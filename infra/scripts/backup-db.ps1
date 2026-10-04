param(
    [string]$OutputDirectory = (Join-Path $PSScriptRoot '../../backups')
)

$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$backupDirectory = [IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Path $backupDirectory -Force | Out-Null
$backupName = 'jobtracker-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N') + '.dump'
$containerPath = '/tmp/' + $backupName
$destination = Join-Path $backupDirectory $backupName

Push-Location $projectRoot
try {
    # Keep the binary archive out of the PowerShell text pipeline.
    docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --no-owner --no-acl --file="$1"' sh $containerPath
    if ($LASTEXITCODE -ne 0) { throw 'Database export failed.' }
    docker compose exec -T db pg_restore --list $containerPath | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Database archive validation failed.' }
    docker compose cp "db:$containerPath" $destination
    if ($LASTEXITCODE -ne 0) { throw 'Copying the archive to this PC failed.' }
    if ((Get-Item -LiteralPath $destination).Length -eq 0) { throw 'Database archive is empty.' }
    Write-Output "Database archive saved to $destination"
    Write-Output 'Archive structure verified. Validate a restore before migrating production data.'
}
finally {
    # This is a uniquely named file created above, never a database volume.
    docker compose exec -T db rm -f $containerPath
    Pop-Location
}
