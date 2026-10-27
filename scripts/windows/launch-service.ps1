param([Parameter(Mandatory=$true)][ValidateSet('web','worker')][string]$Service)
$ErrorActionPreference = 'Stop'
$hubRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$logRoot = Join-Path $hubRoot '.local-data\services'
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
$env:PYTHONUTF8 = '1'
$env:NEXT_TELEMETRY_DISABLED = '1'
$env:NODE_ENV = 'production'
if ($Service -eq 'web') {
    $executable = Join-Path $hubRoot '.runtime\node\node.exe'
    $arguments = '"' + (Join-Path $hubRoot 'apps\web\node_modules\next\dist\bin\next') + '" start --hostname 127.0.0.1 --port 3000'
    $workingDirectory = Join-Path $hubRoot 'apps\web'
} else {
    $executable = Join-Path $hubRoot '.venv\Scripts\python.exe'
    $arguments = '-X utf8 -u -m comfy_hub_worker --run'
    $workingDirectory = Join-Path $hubRoot 'apps\worker'
}
# Archive the previous process logs before each scheduled restart.
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
foreach ($stream in @('stdout','stderr')) {
    $log = Join-Path $logRoot "$Service.$stream.log"
    if (Test-Path -LiteralPath $log) { Move-Item -LiteralPath $log -Destination (Join-Path $logRoot "$Service.$stamp.$stream.log") }
}
$child = Start-Process -FilePath $executable -ArgumentList $arguments -WorkingDirectory $workingDirectory -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logRoot "$Service.stdout.log") -RedirectStandardError (Join-Path $logRoot "$Service.stderr.log")
@{pid=$child.Id;started=(Get-Date).ToString('o');executable=$executable;working_directory=$workingDirectory} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $logRoot "$Service.process.json") -Encoding UTF8
$child.WaitForExit()
exit $child.ExitCode
