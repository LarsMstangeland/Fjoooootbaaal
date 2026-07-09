param(
    [string]$TaskName = "Ticket Listener"
)

$ErrorActionPreference = "Stop"

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Host "Removed Scheduled Task: $TaskName"
