# [Flow: Stage 1 (CPU 베이스 + VNNI/IPEX) -> Stage 2 (Docling 모델/의존성 설치) -> Stage 3 (서비스 코드 복사 및 실행)]
FROM ubuntu:22.04 AS runtime

# 시스템 의존성
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-pip \
    python3-dev \
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
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# PyTorch CPU wheel + Intel Extension for PyTorch (VNNI/OneDNN 최적화)
RUN pip3 install --no-cache-dir torch==2.4.1+cpu torchvision==0.19.1+cpu --index-url https://download.pytorch.org/whl/cpu
RUN pip3 install --no-cache-dir intel-extension-for-pytorch==2.4.0

COPY backend/docling_service/requirements.txt ./requirements.txt
RUN pip3 install --no-cache-dir -r requirements.txt

COPY backend/docling_service/ ./docling_service/

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
EXPOSE 28182

CMD ["uvicorn", "docling_service.main:app", "--host", "0.0.0.0", "--port", "28182"]
