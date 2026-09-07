# ebo-vision — YOLOE seg + YOLO26 depth + BoT-SORT + DINOv2 re-id.
# CPU image (large: torch + models). Weights auto-download on first run into the /weights volume.
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
      git ffmpeg libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*
# CPU-only torch first (no CUDA → much smaller than the default wheel)
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY worker.py /app/worker.py
# run from the weights volume so downloaded weights (incl. mobileclip2_b.ts) persist there
WORKDIR /weights
ENV YOLO_CONFIG_DIR=/weights HF_HOME=/weights/hf PYTHONUNBUFFERED=1
CMD ["python", "/app/worker.py"]
