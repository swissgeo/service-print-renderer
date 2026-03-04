#!/usr/bin/env bash
#
# install_nvidia_container_toolkit.sh
#
# If we want to render with a real GPU instead of SwiftShader in the local docker
# environment, we need to install this on our zbooks... (if...)
# This is more a work in progress to keep some investigations
#
# WHY:
#   The service-print-renderer uses headless Chrome with hardware-accelerated WebGL
#   (ANGLE over Vulkan) to render map tiles. When running inside Docker, Chrome falls
#   back to the SwiftShader software rasterizer because the container has no access
#   to the host's NVIDIA Vulkan driver libraries.
#
#   The NVIDIA Container Toolkit solves this by acting as a Docker runtime plugin: it
#   automatically injects the correct NVIDIA driver libraries and device nodes into any
#   container that requests GPU access via the `deploy.resources.reservations.devices`
#   key in docker-compose.yml. This enables Chrome inside the container to find the
#   host's nvidia_icd.json and use the real GPU instead of SwiftShader.
#
# WHAT THIS SCRIPT DOES:
#   1. Adds the official NVIDIA container toolkit apt repository and its GPG key.
#   2. Installs the nvidia-container-toolkit package.
#   3. Registers the nvidia runtime with the Docker daemon (nvidia-ctk runtime configure).
#   4. Restarts Docker so the new runtime is picked up.
#
# AFTER INSTALLATION:
#   Update docker-compose.yml renderer-info service: replace the `devices:` block with:
#
#     deploy:
#       resources:
#         reservations:
#           devices:
#             - driver: nvidia
#               count: 1
#               capabilities: [gpu]
#
#   Then run:
#     docker compose --env-file=.env --profile renderer-info run --build --rm renderer-info
#
# REFERENCE:
#   https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html

set -euo pipefail

echo "Adding NVIDIA container toolkit GPG key..."
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
  | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg

echo "Adding NVIDIA container toolkit apt repository..."
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
  | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

echo "Installing nvidia-container-toolkit..."
sudo apt-get update -qq
sudo apt-get install -y nvidia-container-toolkit

echo "Registering nvidia runtime with Docker..."
sudo nvidia-ctk runtime configure --runtime=docker

echo "Restarting Docker daemon..."
sudo systemctl restart docker

echo "Done. Verify with: docker run --rm --gpus all nvidia/cuda:12.0-base nvidia-smi"
