# Self-Contained Dockerfile for LeRobot Training
# Optimized for RunPod with /workspace workflow
# Fully portable - installs all dependencies (PyTorch, conda, etc.)
#
# Build command:
#   docker build -f docker_runpod/Dockerfile -t alexkoven/lerobot-grievous-training:latest .
#
# Key features:
# - Self-contained: Installs PyTorch from scratch (no system dependency)
# - Persistent code: Expects repo in /workspace (network volume)
# - Conda environment: Python 3.11, matches development workflow
# - Direct SSH: Fast access without RunPod gateway lag
# - Auto-activation: Environment activates automatically

# Start from NVIDIA CUDA base (Ubuntu 22.04 + CUDA 12.4.1)
ARG CUDA_VERSION=12.4.1
ARG OS_VERSION=22.04
FROM nvidia/cuda:${CUDA_VERSION}-base-ubuntu${OS_VERSION}

# Python version (match setup_runpod.sh)
ARG PYTHON_VERSION=3.11

# Set shell for RUN commands
SHELL ["/bin/bash", "-c"]

# Configure environment
ENV DEBIAN_FRONTEND=noninteractive \
    MUJOCO_GL=egl \
    CUDA_VISIBLE_DEVICES=0

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    software-properties-common \
    build-essential \
    git \
    curl \
    wget \
    libglib2.0-0 \
    libgl1-mesa-glx \
    libegl1-mesa \
    ffmpeg \
    libusb-1.0-0-dev \
    speech-dispatcher \
    libgeos-dev \
    portaudio19-dev \
    cmake \
    pkg-config \
    ninja-build \
    openssh-server \
    sudo \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Configure SSH for direct access (fast, no gateway)
# SSH keys will be injected at runtime via environment variable (SSH_PUBLIC_KEY)
# This keeps keys out of the image for security
RUN mkdir -p /run/sshd /root/.ssh \
    && chmod 700 /root/.ssh \
    && sed -i 's/#PermitRootLogin prohibit-password/PermitRootLogin yes/' /etc/ssh/sshd_config \
    && sed -i 's/#PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config \
    && sed -i 's/#PubkeyAuthentication yes/PubkeyAuthentication yes/' /etc/ssh/sshd_config

# Install uv for faster package installation
RUN curl -LsSf https://astral.sh/uv/install.sh | sh \
    && mv /root/.local/bin/uv /usr/local/bin/uv

# Install Miniconda
ENV MINICONDA_VERSION=py311_24.7.1-0
RUN wget --quiet https://repo.anaconda.com/miniconda/Miniconda3-${MINICONDA_VERSION}-Linux-x86_64.sh -O /tmp/miniconda.sh \
    && bash /tmp/miniconda.sh -b -p /opt/conda \
    && rm /tmp/miniconda.sh \
    && /opt/conda/bin/conda clean -a -y

# Add conda to PATH
ENV PATH=/opt/conda/bin:$PATH

# Initialize conda for bash
RUN conda init bash

# Create the 'grievous' conda environment with Python 3.11
# This matches setup_runpod.sh and development workflow
RUN conda create -y -n grievous python=${PYTHON_VERSION} \
    && conda clean -a -y

# Configure conda to use 'grievous' environment by default
ENV CONDA_DEFAULT_ENV=grievous \
    CONDA_PREFIX=/opt/conda/envs/grievous

# Copy pyproject.toml for dependency installation
# Install SmolVLA dependencies but NOT lerobot itself
# User will clone Grievous repo to /workspace and install in editable mode
COPY pyproject.toml README.md MANIFEST.in /tmp/lerobot-install/

# Install PyTorch and SmolVLA dependencies (but not lerobot package itself)
# Using PyTorch 2.4.x (tested and confirmed working)
RUN source /opt/conda/etc/profile.d/conda.sh \
    && conda activate grievous \
    && cd /tmp/lerobot-install \
    && uv pip install --system --no-cache \
        "torch>=2.4.0,<2.5.0" \
        "torchvision>=0.19.0,<0.20.0" \
    && uv pip install --system --no-cache \
        "transformers>=4.50.0,<5.0.0" \
        "accelerate>=0.36.0,<2.0.0" \
        "diffusers>=0.31.0,<2.0.0" \
        "datasets>=2.16.0,<5.0.0" \
        "huggingface-hub>=0.28.0,<2.0.0" \
        "safetensors>=0.4.1,<2.0.0" \
        "wandb>=0.20.0,<0.22.0" \
        "pillow>=10.2.0" \
        "opencv-python>=4.9.0.80" \
        "gymnasium>=1.0.0" \
        "imageio[ffmpeg]>=2.34.0,<3.0.0" \
        "numpy>=2.0.0,<3.0.0" \
        "pyarrow>=17.0.0,<20.0.0" \
        "pydantic>=2.7.0,<3.0.0" \
        "torchcodec>=0.2.1,<0.6.0; sys_platform != 'win32' and (sys_platform != 'linux' or (platform_machine != 'aarch64' and platform_machine != 'arm64' and platform_machine != 'armv7l')) and (sys_platform != 'darwin' or platform_machine != 'x86_64')" \
    && rm -rf /tmp/lerobot-install \
    && conda clean -a -y

# Verify PyTorch installation
RUN source /opt/conda/etc/profile.d/conda.sh \
    && conda activate grievous \
    && python -c "import torch; print(f'PyTorch {torch.__version__} installed'); print(f'CUDA available: {torch.cuda.is_available()}')"

# Create /workspace directory structure
# This is where persistent data (code, datasets, models) lives
RUN mkdir -p /workspace/.cache/pip \
    && mkdir -p /workspace/.cache/huggingface \
    && mkdir -p /workspace/.cache/torch \
    && mkdir -p /workspace/.cache/triton \
    && mkdir -p /workspace/tmp

# Set environment variables for cache directories
# Point to /workspace so they persist with network volume
ENV TMPDIR=/workspace/tmp \
    TEMP=/workspace/tmp \
    TMP=/workspace/tmp \
    HF_HOME=/workspace/.cache/huggingface \
    HF_LEROBOT_HOME=/workspace/.cache/huggingface/lerobot \
    TORCH_HOME=/workspace/.cache/torch \
    TRITON_CACHE_DIR=/workspace/.cache/triton \
    PIP_CACHE_DIR=/workspace/.cache/pip \
    XDG_CACHE_HOME=/workspace/.cache

# Configure bash to auto-activate conda environment
# Every shell session will have 'grievous' activated
RUN echo 'source /opt/conda/etc/profile.d/conda.sh' >> /root/.bashrc \
    && echo 'conda activate grievous' >> /root/.bashrc \
    && echo 'cd /workspace' >> /root/.bashrc

# Copy entrypoint script
COPY docker_runpod/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Set working directory to /workspace
# This is where your cloned repo will be
WORKDIR /workspace

# Expose ports
# 22: SSH (direct access, fast)
# 5555: ZMQ command socket (for inference)
# 5556: ZMQ observation socket (for inference)
EXPOSE 22 5555 5556

# Set entrypoint and default command
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["sleep", "infinity"]
