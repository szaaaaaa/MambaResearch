# Extract metrics for one run.
param([Parameter(Mandatory=$true)][string]$RunId)

$base = "http://127.0.0.1:8010/api/runs/$RunId"
$out = [ordered]@{}
$out.run_id = $RunId

try {
    $events = Invoke-RestMethod -Uri "$base/events" -TimeoutSec 30
} catch {
    Write-Output "ERR_EVENTS: $($_.Exception.Message)"; return
}

$out.events_total = $events.Count
$out.replan_count = @($events | Where-Object { $_.type -eq 'replan' }).Count
$out.tool_invoke_pairs = (@($events | Where-Object { $_.type -eq 'tool_invoke' }).Count) / 2
$out.skill_invoke_pairs = (@($events | Where-Object { $_.type -eq 'skill_invoke' }).Count) / 2
$out.artifacts_created = @($events | Where-Object { $_.type -eq 'artifact_created' }).Count

if ($events.Count -gt 0) {
    $first = [datetime]$events[0].ts
    $last = [datetime]$events[-1].ts
    $out.wall_time_sec = [math]::Round(($last - $first).TotalSeconds, 1)
    $out.first_ts = $events[0].ts
    $out.last_ts = $events[-1].ts
}

$term = $events | Where-Object { $_.type -eq 'run_terminate' } | Select-Object -First 1
if ($term) { $out.terminate_reason = $term.reason }

try {
    $state = Invoke-RestMethod -Uri "$base/state" -TimeoutSec 15
    $out.status = $state.status
    if ($state.route_plan) { $out.planning_iteration = $state.route_plan.planning_iteration }
    $node_status = $state.node_status
    $needs_replan = 0
    foreach ($k in $node_status.PSObject.Properties.Name) {
        if ($node_status.$k -eq 'needs_replan') { $needs_replan++ }
    }
    $out.nodes_needs_replan = $needs_replan
    $out.report_text_len = if ($state.report_text) { $state.report_text.Length } else { 0 }
} catch {
    $out.state_err = $_.Exception.Message
}

try {
    $arts = Invoke-RestMethod -Uri "$base/artifacts" -TimeoutSec 15
    $report = $arts | Where-Object { $_.artifact_type -eq 'ResearchReport' } | Select-Object -First 1
    if ($report) {
        $out.report_artifact_id = $report.artifact_id
        $detail = Invoke-RestMethod -Uri "$base/artifacts/$($report.artifact_id)" -TimeoutSec 15
        $out.report_payload_len = if ($detail.payload.report) { $detail.payload.report.Length } else { 0 }
        $out.report_artifact_count = $detail.payload.artifact_count
    } else {
        $out.report_artifact_id = $null
    }
    $out.artifact_types = ($arts | ForEach-Object { $_.artifact_type }) -join ','
} catch {
    $out.artifacts_err = $_.Exception.Message
}

try {
    $req = [System.Net.HttpWebRequest]::Create("$base/report.pdf")
    $req.Method = 'GET'
    $req.Timeout = 15000
    $resp = $req.GetResponse()
    $out.pdf_status = [int]$resp.StatusCode
    $out.pdf_bytes = $resp.ContentLength
    $resp.Close()
} catch {
    $out.pdf_err = $_.Exception.Message
}

$out | ConvertTo-Json -Depth 4
