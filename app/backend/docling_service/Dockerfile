# [Flow: Stage 1 (CPU 베이스 + Python 3.12) -> Stage 2 (PyTorch CPU + Docling 설치) -> Stage 3 (RapidOCR 한국어 모델 다운로드) -> Stage 4 (서비스 코드 복사 및 실행)]
FROM ubuntu:22.04 AS runtime

# 시스템 의존성
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    gnupg \
    build-essential \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    poppler-utils \
    software-properties-common \
    imagemagick \
    ffmpeg \
    && add-apt-repository -y ppa:alex-p/tesseract-ocr5 \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-kor \
    tesseract-ocr-jpn \
    tesseract-ocr-eng \
    libtesseract-dev \
    libleptonica-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Tesseract 언어 모델 경로
ENV TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata

# Tesseract 5.x 고품질 언어 모델 (tessdata_best = 정확도 우선)
RUN mkdir -p /usr/share/tesseract-ocr/5/tessdata && \
    curl -fsSL -o /usr/share/tesseract-ocr/5/tessdata/eng.traineddata https://github.com/tesseract-ocr/tessdata_best/raw/main/eng.traineddata && \
    curl -fsSL -o /usr/share/tesseract-ocr/5/tessdata/kor.traineddata https://github.com/tesseract-ocr/tessdata_best/raw/main/kor.traineddata && \
    curl -fsSL -o /usr/share/tesseract-ocr/5/tessdata/kor_vert.traineddata https://github.com/tesseract-ocr/tessdata_best/raw/main/kor_vert.traineddata && \
    curl -fsSL -o /usr/share/tesseract-ocr/5/tessdata/jpn.traineddata https://github.com/tesseract-ocr/tessdata_best/raw/main/jpn.traineddata && \
    curl -fsSL -o /usr/share/tesseract-ocr/5/tessdata/jpn_vert.traineddata https://github.com/tesseract-ocr/tessdata_best/raw/main/jpn_vert.traineddata && \
    curl -fsSL -o /usr/share/tesseract-ocr/5/tessdata/osd.traineddata https://github.com/tesseract-ocr/tessdata/raw/main/osd.traineddata && \
    chmod 644 /usr/share/tesseract-ocr/5/tessdata/*.traineddata

# Python 3.12 standalone binary (Docling v2.107+ requires >=3.12)
RUN curl -fsSL https://github.com/astral-sh/python-build-standalone/releases/download/20250409/cpython-3.12.10+20250409-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz -o /tmp/python3.12.tar.gz \
    && tar -xzf /tmp/python3.12.tar.gz -C /usr/local \
    && rm -f /tmp/python3.12.tar.gz \
    && ln -sf /usr/local/python/bin/python3.12 /usr/local/bin/python3.12 \
    && ln -sf /usr/local/python/bin/python3.12 /usr/local/bin/python3 \
    && ln -sf /usr/local/python/bin/pip3.12 /usr/local/bin/pip3

WORKDIR /app

# pip 최신화
RUN python3.12 -m pip install --no-cache-dir --upgrade pip

# PyTorch CPU wheel (순정, IPEX 없음)
RUN python3.12 -m pip install --no-cache-dir torch==2.8.0+cpu torchvision==0.23.0+cpu --index-url https://download.pytorch.org/whl/cpu

COPY backend/docling_service/requirements.txt ./requirements.txt
RUN python3.12 -m pip install --no-cache-dir -r requirements.txt

# RapidOCR v3는 자동으로 모델을 다운로드하므로 수동 다운로드 불필요
# 모델은 첫 사용 시 modelscope.cn에서 자동 다운로드됨

ENV DOCLING_NUM_THREADS=2
ENV OMP_NUM_THREADS=2
ENV INFERENCE_NUM_THREADS=2
ENV OCR_ENGINE=tesseract
ENV OCR_LANG=ko+en+ja

COPY backend/docling_service/ ./docling_service/

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
EXPOSE 28182

CMD ["python3.12", "-m", "uvicorn", "docling_service.main:app", "--host", "0.0.0.0", "--port", "28182"]
