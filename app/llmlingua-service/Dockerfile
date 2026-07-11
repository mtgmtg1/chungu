# [Flow: Step 1 (Python 베이스 이미지) -> Step 2 (llmlingua + OpenVINO + NNCF 설치)
#       -> Step 3 (모델 사전 다운로드) -> Step 4 (OpenVINO INT8 변환)
#       -> Step 5 (uvicorn 서버 시작)]
# LLMLingua-2 프롬프트 압축 마이크로서비스 컨테이너.
# Node.js AI 백엔드가 도구 결과 압축을 요청할 때 사용한다.
# OpenVINO INT8 양자화로 CPU 추론 속도 2~4x 향상.

FROM python:3.11-slim AS builder

WORKDIR /app

# 시스템 의존성 (torch/transformers/openvino용)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY llmlingua-service/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# [Flow: 모델 사전 다운로드 — 런타임 지연 방지]
# 서버 시작 시 다운로드하면 첫 요청이 지연되므로 빌드 시 미리 다운로드한다
# CUDA_VISIBLE_DEVICES="" 로 GPU 인식 차단 — CPU 전용 모드로 모델 로드
ENV CUDA_VISIBLE_DEVICES=""
RUN python -c "from llmlingua import PromptCompressor; PromptCompressor(model_name='microsoft/llmlingua-2-bert-base-multilingual-cased-meetingbank', use_llmlingua2=True, device_map='cpu')"

# [Flow: OpenVINO INT8 변환 — NNCF Post-Training Quantization]
# 1. HF 모델 로드 + 어휘 확장 ([NEW0]..[NEW99] 특수 토큰 추가)
# 2. OpenVINO FP32 형식으로 변환
# 3. NNCF 로 INT8 양자화 (가중치 + 활성화)
# 4. /app/ov_model_int8 에 저장
COPY llmlingua-service/convert_to_openvino.py ./convert_to_openvino.py
RUN python convert_to_openvino.py

# --- Runtime stage ---
FROM python:3.11-slim AS runtime

WORKDIR /app

# 런타임에 필요한 최소 시스템 패키지
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# builder 스테이지에서 설치된 패키지 복사
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /root/.cache/huggingface /root/.cache/huggingface

# [Flow: OpenVINO INT8 모델 복사 — 변환 스크립트가 생성한 양자화된 모델]
COPY --from=builder /app/ov_model_int8 /app/ov_model_int8

COPY llmlingua-service/main.py ./main.py

ENV PYTHONUNBUFFERED=1
ENV HF_HOME=/root/.cache/huggingface
# [Flow: CPU 전용 모드 — GPU 없는 서버에서 torch CUDA 초기화 실패 방지]
ENV CUDA_VISIBLE_DEVICES=""
# [Flow: OpenVINO INT8 모델 경로 — main.py 가 이 경로에서 모델을 로드]
ENV LLMLINGUA_OV_MODEL_DIR=/app/ov_model_int8
EXPOSE 8000

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
