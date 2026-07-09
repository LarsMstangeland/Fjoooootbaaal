param(
    [string]$Config = "config.toml"
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $RepoRoot "logs"
$LogFile = Join-Path $LogDir "ticket-listener.log"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

Start-Process `
    -FilePath "uv" `
    -ArgumentList @("run", "python", "-m", "ticket_listener.cli", "--config", $Config) `
    -WorkingDirectory $RepoRoot `
    -RedirectStandardOutput $LogFile `
    -RedirectStandardError $LogFile `
    -WindowStyle Hidden

Write-Host "ticket-listener started in background. Log: $LogFile"
