param([ValidateSet('install','start','stop','status','logs')][string]$Action='status', [int]$Tail=60)
$ErrorActionPreference = 'Stop'
$hubRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$launcher = Join-Path $PSScriptRoot 'launch-service.ps1'
$taskPrefix = 'ComfyUI-Cloud-Hub-G58-'
$taskNames = @(($taskPrefix + 'Web'), ($taskPrefix + 'Worker'))
$powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
function Assert-HubTask($task) {
    if ($task.Actions.Count -ne 1 -or $task.Actions[0].Execute -ne $powershell -or $task.Actions[0].Arguments -notlike ('*"' + $launcher + '"*')) {
        throw "Task name collision: $($task.TaskName). No unrelated task was modified."
    }
}
if ($Action -eq 'install') {
    $hubUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    foreach ($service in @('web','worker')) {
        $name = $taskPrefix + $(if ($service -eq 'web') {'Web'} else {'Worker'})
        $existing = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
        if ($existing) { Assert-HubTask $existing; continue }
        $arguments = '-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $launcher + '" -Service ' + $service
        $taskAction = New-ScheduledTaskAction -Execute $powershell -Argument $arguments -WorkingDirectory $hubRoot
        $trigger = New-ScheduledTaskTrigger -AtLogOn -User $hubUser
        $principal = New-ScheduledTaskPrincipal -UserId $hubUser -LogonType Interactive -RunLevel Limited
        $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 99 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
        Register-ScheduledTask -TaskName $name -Action $taskAction -Trigger $trigger -Principal $principal -Settings $settings -Description "G58 private studio $service; independent of Codex. H3 is managed separately." | Out-Null
    }
    Write-Output 'Installed two independent scheduled tasks; automatic start after Admin signs in.'
    exit
}
if ($Action -eq 'logs') {
    Get-ChildItem -LiteralPath (Join-Path $hubRoot '.local-data\services') -Filter '*.log' | Where-Object Name -in @('web.stdout.log','web.stderr.log','worker.stdout.log','worker.stderr.log') | ForEach-Object { Write-Output $_.FullName; Get-Content -LiteralPath $_.FullName -Tail $Tail -Encoding UTF8 }
    exit
}
foreach ($name in $taskNames) { Assert-HubTask (Get-ScheduledTask -TaskName $name) }
if ($Action -eq 'stop') {
    & (Join-Path $hubRoot '.runtime\python312\python.exe') -X utf8 (Join-Path $PSScriptRoot 'guarded-stop.py')
    exit $LASTEXITCODE
}
if ($Action -eq 'start') {
    foreach ($name in $taskNames) {
        if ((Get-ScheduledTask -TaskName $name).State -ne 'Running') { Start-ScheduledTask -TaskName $name }
        if ($name.EndsWith('Web')) {
            $ready = $false
            for ($attempt=0; $attempt -lt 30; $attempt++) {
                try { $null=Invoke-WebRequest -Uri 'http://127.0.0.1:3000/api/health' -UseBasicParsing -TimeoutSec 2; $ready=$true; break } catch { Start-Sleep -Seconds 1 }
            }
            if (-not $ready) { throw 'Web did not become ready. Inspect logs before retrying.' }
        }
    }
}
foreach ($name in $taskNames) {
    $task = Get-ScheduledTask -TaskName $name
    $info = Get-ScheduledTaskInfo -TaskName $name
    [pscustomobject]@{Task=$name;State=[string]$task.State;LastRun=$info.LastRunTime;LastResult=$info.LastTaskResult;NextRun=$info.NextRunTime} | Format-List
}
try {
    $state = Invoke-RestMethod -Uri 'http://127.0.0.1:3000/api/mvp/state' -TimeoutSec 5
    [pscustomobject]@{Website='online';Jobs=$state.jobs.Count;Active=@($state.jobs | Where-Object status -in @('queued','claimed','running','uploading')).Count;Worker=$state.worker} | ConvertTo-Json -Depth 4
} catch { Write-Output 'Website is offline.' }
