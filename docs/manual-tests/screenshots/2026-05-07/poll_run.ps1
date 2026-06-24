# Poll a run until run_terminate event appears or timeout (default 1800s).
param(
    [Parameter(Mandatory=$true)][string]$RunId,
    [int]$TimeoutSec = 1800,
    [int]$IntervalSec = 30,
    [string]$LogPath = $null
)

$start = Get-Date
$baseUrl = "http://127.0.0.1:8010/api/runs/$RunId/events"
$lastCount = 0
$lastTypes = ""
while (((Get-Date) - $start).TotalSeconds -lt $TimeoutSec) {
    try {
        $events = Invoke-RestMethod -Uri $baseUrl -TimeoutSec 15
        $count = $events.Count
        $terminated = $events | Where-Object { $_.type -eq 'run_terminate' }
        $replans = ($events | Where-Object { $_.type -eq 'replan' }).Count
        $artifacts = ($events | Where-Object { $_.type -eq 'artifact_created' }).Count
        $obsLast = ($events | Where-Object { $_.type -eq 'observation' } | Select-Object -Last 1)
        $lastWhat = if ($obsLast) { $obsLast.observation.what_happened } else { '' }
        $elapsed = [int]((Get-Date) - $start).TotalSeconds
        $line = "[t+${elapsed}s] events=$count replans=$replans artifacts=$artifacts last=$lastWhat"
        Write-Output $line
        if ($LogPath) { Add-Content -Path $LogPath -Value $line -Encoding utf8 }
        if ($terminated) {
            Write-Output "TERMINATED reason=$($terminated.reason)"
            if ($LogPath) { Add-Content -Path $LogPath -Value "TERMINATED reason=$($terminated.reason)" -Encoding utf8 }
            return 0
        }
    } catch {
        Write-Output ("ERR: " + $_.Exception.Message)
    }
    Start-Sleep -Seconds $IntervalSec
}
Write-Output "TIMEOUT after ${TimeoutSec}s"
if ($LogPath) { Add-Content -Path $LogPath -Value "TIMEOUT after ${TimeoutSec}s" -Encoding utf8 }
return 1
