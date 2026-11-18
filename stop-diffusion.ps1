$ErrorActionPreference = "Stop"
$INST = $PSScriptRoot
$PIDFILE = Join-Path $INST ".diffusion.pid"
$Port = if ($env:DIFFUSION_PORT) { $env:DIFFUSION_PORT } else { "8189" }

function Test-WorkerProcess($proc) {
    if (-not $proc -or -not $proc.CommandLine) { return $false }
    return ($proc.CommandLine -like '*diffusion\worker.py*' -or
            $proc.CommandLine -like '*diffusion/worker.py*')
}

$targets = @()

if (Test-Path $PIDFILE) {
    $procId = (Get-Content $PIDFILE -Raw).Trim()
    Remove-Item $PIDFILE -Force
    if ($procId) {
        $info = Get-CimInstance Win32_Process -Filter "ProcessId=$procId" -ErrorAction SilentlyContinue
        if (Test-WorkerProcess $info) { $targets += $info }
    }
}

if (-not $targets) {
    $targets = @(Get-CimInstance Win32_Process | Where-Object { Test-WorkerProcess $_ })
}

$connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
foreach ($conn in $connections) {
    $info = Get-CimInstance Win32_Process -Filter "ProcessId=$($conn.OwningProcess)" -ErrorAction SilentlyContinue
    if ($info -and ($info.Name -like 'python*' -or $info.CommandLine -like '*worker.py*')) {
        $targets += $info
    }
}

$targets = @($targets | Sort-Object ProcessId -Unique)
if (-not $targets) {
    Write-Host "No diffusion worker process found."
    exit 0
}

foreach ($target in $targets) {
    Stop-Process -Id $target.ProcessId -ErrorAction SilentlyContinue
}

for ($i = 0; $i -lt 20; $i++) {
    $alive = @($targets | Where-Object { Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue })
    if (-not $alive) {
        Write-Host ("Diffusion worker stopped (PID {0})." -f (($targets.ProcessId) -join ', '))
        exit 0
    }
    Start-Sleep -Milliseconds 250
}

foreach ($target in $targets) {
    Stop-Process -Id $target.ProcessId -Force -ErrorAction SilentlyContinue
}
Write-Host ("Diffusion worker force-stopped (PID {0})." -f (($targets.ProcessId) -join ', '))
