# [Flow: Step 1 (Python 베이스) -> Step 2 (FastAPI + requests 설치) -> Step 3 (AI Studio API 프록시 서비스 기동)]
# PaddleOCR AI Studio API 프록시 컨테이너: 외부 API 호출을 내부로 캡슐화
# 클라이언트에 API 토큰 노출 없이 폴백 OCR 서비스 제공

FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# LibreOffice + CJK 폰트 설치 (오피스 문서 → PDF 변환용)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-core libreoffice-writer libreoffice-impress libreoffice-calc \
    fonts-noto-cjk fonts-noto-cjk-extra \
    && rm -rf /var/lib/apt/lists/*

# FastAPI + 의존성 설치
RUN pip install --no-cache-dir fastapi uvicorn python-multipart PyMuPDF requests

# 서비스 코드 복사
COPY backend/paddleocr_service/main.py /app/main.py

WORKDIR /app

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
