# [Flow: Stage 1 (CPU 베이스 + Python 3.12) -> Stage 2 (PyTorch/IPEX + Surya OCR 설치) -> Stage 3 (서비스 코드 복사 및 실행)]
FROM ubuntu:22.04 AS runtime

# 시스템 의존성
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    poppler-utils \
    tesseract-ocr \
    tesseract-ocr-kor \
    tesseract-ocr-eng \
    imagemagick \
    ffmpeg \
    numactl \
    && rm -rf /var/lib/apt/lists/*

# Python 3.12 standalone binary (docling-surya requires >=3.12)
RUN curl -fsSL https://github.com/astral-sh/python-build-standalone/releases/download/20250409/cpython-3.12.10+20250409-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz -o /tmp/python3.12.tar.gz \
    && tar -xzf /tmp/python3.12.tar.gz -C /usr/local \
    && rm -f /tmp/python3.12.tar.gz \
    && ln -sf /usr/local/python/bin/python3.12 /usr/local/bin/python3.12 \
    && ln -sf /usr/local/python/bin/python3.12 /usr/local/bin/python3 \
    && ln -sf /usr/local/python/bin/pip3.12 /usr/local/bin/pip3

WORKDIR /app

# pip 최신화 (metadata 2.3 wheel 인식)
RUN python3.12 -m pip install --no-cache-dir --upgrade pip

# PyTorch CPU wheel + Intel Extension for PyTorch (VNNI/OneDNN 최적화)
RUN python3.12 -m pip install --no-cache-dir torch==2.8.0+cpu torchvision==0.23.0+cpu --index-url https://download.pytorch.org/whl/cpu
RUN python3.12 -m pip install --no-cache-dir intel-extension-for-pytorch==2.8.0

COPY backend/docling_service/requirements.txt ./requirements.txt
RUN python3.12 -m pip install --no-cache-dir -r requirements.txt

COPY backend/docling_service/ ./docling_service/

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
EXPOSE 28182

CMD ["python3.12", "-m", "uvicorn", "docling_service.main:app", "--host", "0.0.0.0", "--port", "28182"]
