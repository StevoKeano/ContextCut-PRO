#!/bin/bash
# Install the isolated diffusion worker environment (Linux/WSL + NVIDIA CUDA).
set -e
INST="$(dirname "$0")"
INSTALL_DIR="${INSTALL_DIR:-$INST}"
VENV="$INSTALL_DIR/diffusion-venv"
LOCK="$INST/requirements-diffusion.lock.txt"

mkdir -p "$INSTALL_DIR/outputs/images"

if [ ! -x "$VENV/bin/python" ]; then
  echo "Creating diffusion venv at $VENV..."
  python3 -m venv "$VENV"
fi

source "$VENV/bin/activate"
pip install --upgrade pip -q

echo "Installing CUDA PyTorch and diffusion dependencies in one pass..."
pip install -U \
  "torch==2.14.1+cu126" \
  "torchvision==0.29.1+cu126" \
  diffusers transformers accelerate safetensors pillow sentencepiece \
  --extra-index-url https://download.pytorch.org/whl/cu126

echo "Verifying pipeline imports..."
"$VENV/bin/python" - <<'PY'
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
PY

pip freeze > "$LOCK"
echo "Pinned installed versions to $LOCK"

deactivate
echo "Diffusion worker installed. Start it with ./start-diffusion.sh"
