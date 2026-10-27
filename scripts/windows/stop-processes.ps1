# Invoked only by guarded-stop.py with the queue database write-locked.
$ErrorActionPreference='Stop'
$hubRoot=Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
foreach($taskName in @('ComfyUI-Cloud-Hub-G58-Worker','ComfyUI-Cloud-Hub-G58-Web')) {
    Stop-ScheduledTask -TaskName $taskName
}
function Get-HubProcesses {
    Get-CimInstance Win32_Process | Where-Object {
        ($_.ExecutablePath -eq (Join-Path $hubRoot '.runtime\node\node.exe') -and $_.CommandLine.Contains((Join-Path $hubRoot 'apps\web\node_modules\next\dist\bin\next'))) -or
        ($_.ExecutablePath -in @((Join-Path $hubRoot '.venv\Scripts\python.exe'),(Join-Path $hubRoot '.runtime\python312\python.exe')) -and $_.CommandLine -match '-m comfy_hub_worker --run')
    }
}
# Start-Process children can outlive their scheduled-task wrapper. Identify them
# by this project's executable AND command line, never by the generic process name.
foreach($owned in @(Get-HubProcesses)) {
    $current=Get-CimInstance Win32_Process -Filter "ProcessId=$($owned.ProcessId)" -ErrorAction SilentlyContinue
    if($current -and $current.CreationDate -eq $owned.CreationDate -and $current.ExecutablePath -eq $owned.ExecutablePath) {
        & "$env:SystemRoot\System32\taskkill.exe" /PID $owned.ProcessId /T /F 2>$null | Out-Null
    }
}
Start-Sleep -Milliseconds 300
if(@(Get-HubProcesses).Count) {throw 'Project processes remain after stop.'}
