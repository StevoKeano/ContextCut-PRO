$ErrorActionPreference = "Stop"
$INST = $PSScriptRoot
$VENV = Join-Path $INST "diffusion-venv"
$PY = Join-Path $VENV "Scripts\python.exe"
$WORKER = Join-Path $INST "diffusion\worker.py"
$PIDFILE = Join-Path $INST ".diffusion.pid"
$OUTLOG = Join-Path $INST "diffusion_worker.log"
$ERRLOG = Join-Path $INST "diffusion_worker.err.log"
$Port = if ($env:DIFFUSION_PORT) { $env:DIFFUSION_PORT } else { "8189" }

function Test-WorkerProcess($proc) {
    if (-not $proc -or -not $proc.CommandLine) { return $false }
    return ($proc.CommandLine -like '*diffusion\worker.py*' -or
            $proc.CommandLine -like '*diffusion/worker.py*')
}

if (-not (Test-Path $PY)) {
    throw "Missing $PY - run install-diffusion.ps1 first."
}
if (-not (Test-Path $WORKER)) {
    throw "Missing worker at $WORKER"
}

if (Test-Path $PIDFILE) {
    $oldId = (Get-Content $PIDFILE -Raw).Trim()
    if ($oldId) {
        $oldInfo = Get-CimInstance Win32_Process -Filter "ProcessId=$oldId" -ErrorAction SilentlyContinue
        if (Test-WorkerProcess $oldInfo) {
            Write-Host "Diffusion worker already running (PID $oldId)."
            exit 0
        }
    }
    Remove-Item $PIDFILE -Force
}

$listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
foreach ($conn in $listeners) {
    $info = Get-CimInstance Win32_Process -Filter "ProcessId=$($conn.OwningProcess)" -ErrorAction SilentlyContinue
    if (-not $info) { continue }
    if ($info.CommandLine -like '*worker.py*') {
        Write-Host ("Diffusion worker already listening on port {0} (PID {1})." -f $Port, $info.ProcessId)
        exit 0
    }
    Write-Error ("Port {0} is in use by PID {1} ({2}). Stop it or set DIFFUSION_PORT." -f $Port, $info.ProcessId, $info.Name)
    exit 1
}

$BindHost = if ($env:DIFFUSION_HOST) { $env:DIFFUSION_HOST } else { "0.0.0.0" }
$PublicHost = if ($env:DIFFUSION_PUBLIC_HOST) {
    $env:DIFFUSION_PUBLIC_HOST
} else {
    "192.168.137.1"
}
$OutputDir = if ($env:DIFFUSION_OUTPUT_DIR) {
    $env:DIFFUSION_OUTPUT_DIR
} else {
    Join-Path $INST "outputs\images"
}
$ModelRoot = if ($env:DIFFUSION_MODEL_ROOT) {
    $env:DIFFUSION_MODEL_ROOT
} else {
    Join-Path $INST "models\official"
}
$HFHome = if ($env:HF_HOME) {
    $env:HF_HOME
} else {
    Join-Path $INST "hf-cache"
}
$IdleTimeout = if ($env:DIFFUSION_IDLE_TIMEOUT) {
    $env:DIFFUSION_IDLE_TIMEOUT
} else {
    "900"
}

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

$env:DIFFUSION_HOST = $BindHost
$env:DIFFUSION_PORT = $Port
$env:DIFFUSION_PUBLIC_HOST = $PublicHost
$env:DIFFUSION_OUTPUT_DIR = $OutputDir
$env:DIFFUSION_MODEL_ROOT = $ModelRoot
$env:DIFFUSION_IDLE_TIMEOUT = $IdleTimeout
$env:HF_HOME = $HFHome
$env:HF_HUB_CACHE = Join-Path $HFHome "hub"
$env:HF_HUB_DISABLE_SYMLINKS_WARNING = "1"

$proc = Start-Process `
    -FilePath $PY `
    -ArgumentList @("`"$WORKER`"") `
    -WorkingDirectory $INST `
    -PassThru `
    -RedirectStandardOutput $OUTLOG `
    -RedirectStandardError $ERRLOG `
    -WindowStyle Hidden
$proc.Id | Set-Content -Path $PIDFILE -Encoding ascii

for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 1
    $owners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess)
    foreach ($owner in $owners) {
        $ownerInfo = Get-CimInstance Win32_Process -Filter "ProcessId=$owner" -ErrorAction SilentlyContinue
        if ($ownerInfo -and ((Test-WorkerProcess $ownerInfo) -or $ownerInfo.Name -like 'python*')) {
            $ownerInfo.ProcessId | Set-Content -Path $PIDFILE -Encoding ascii
            Write-Host ("Diffusion worker ready at http://{0}:{1} (PID {2})." -f $PublicHost, $Port, $ownerInfo.ProcessId)
            exit 0
        }
    }
    if ($owners) {
        Write-Error ("Port {0} is owned by another process (PID {1}); new worker did not bind. See {2}" -f $Port, (($owners) -join ', '), $ERRLOG)
        exit 1
    }
    if (-not (Get-Process -Id $proc.Id -ErrorAction SilentlyContinue)) {
        Write-Error "Worker process exited during startup. See $ERRLOG"
        exit 1
    }
}

Write-Error "Worker did not bind port $Port within 60s. See $OUTLOG and $ERRLOG"
exit 1
