FROM python:3.11-slim

# opencv (pulled in transitively by ultralytics even though we request the headless
# build) needs these even in headless mode on Debian slim.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 libxcb1 libsm6 libxext6 libxrender1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
# Install CPU-only torch/torchvision first so ultralytics' dependency resolution
# finds them already satisfied and never pulls the (huge, GPU-only) CUDA wheels --
# this host has no GPU, and skipping CUDA saves several minutes and several GB.
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/

WORKDIR /app/src

# Cloud Run injects PORT at runtime (defaults to 8080); fall back to 8080 for local
# `docker run` too. Shell form (not exec/JSON form) is required for $PORT to expand.
EXPOSE 8080
CMD gunicorn --worker-class gthread --threads 2 -w 1 --timeout 120 --bind 0.0.0.0:${PORT:-8080} app:app
