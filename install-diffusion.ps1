param(
    [string]$AllowedRemote = "192.168.137.0/24"
)

$ErrorActionPreference = "Stop"
$INST = $PSScriptRoot
$VENV = Join-Path $INST "diffusion-venv"
$PY = Join-Path $VENV "Scripts\python.exe"
$LOCK = Join-Path $INST "requirements-diffusion.lock.txt"
$OUTDIR = Join-Path $INST "outputs\images"
$RuleName = "ContextCut Diffusion Worker (8189)"

$principal = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this script from an elevated PowerShell (Administrator)."
}

New-Item -ItemType Directory -Force -Path $OUTDIR | Out-Null

if (-not (Test-Path $PY)) {
    Write-Host "Creating diffusion venv at $VENV..."
    python -m venv $VENV
}

& $PY -m pip install --upgrade pip -q

Write-Host "Installing CUDA PyTorch and diffusion dependencies in one pass..."
$pipArgs = @(
    "install",
    "-U",
    "torch==2.14.1+cu126",
    "torchvision==0.29.1+cu126",
    "diffusers",
    "transformers",
    "accelerate",
    "safetensors",
    "pillow",
    "sentencepiece",
    "--extra-index-url",
    "https://download.pytorch.org/whl/cu126"
)
& $PY -m pip @pipArgs

Write-Host "Verifying pipeline imports..."
@'
import torch

assert torch.cuda.is_available(), "CUDA is not available! Check PyTorch wheel index."

from diffusers import (
    Flux2KleinPipeline,
    ZImageImg2ImgPipeline,
    ZImageInpaintPipeline,
    ZImagePipeline,
)

print("torch", torch.__version__, "cuda available:", torch.cuda.is_available())
print("pipelines ok:", [c.__name__ for c in (
    ZImagePipeline,
    ZImageImg2ImgPipeline,
    ZImageInpaintPipeline,
    Flux2KleinPipeline,
)])
'@ | & $PY -

& $PY -m pip freeze | Set-Content -Path $LOCK -Encoding ascii
Write-Host "Pinned installed versions to $LOCK"

Write-Host "Opening inbound TCP 8189 for $AllowedRemote..."
Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue |
    Remove-NetFirewallRule
New-NetFirewallRule `
    -DisplayName $RuleName `
    -Direction Inbound `
    -Protocol TCP `
    -LocalPort 8189 `
    -Action Allow `
    -Profile Private `
    -RemoteAddress $AllowedRemote | Out-Null

Write-Host "Diffusion worker installed. Start it with .\start-diffusion.ps1"
