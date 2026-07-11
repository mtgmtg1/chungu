# [Flow: Step 1 (FastAPI 서버 시작) -> Step 2 (LLMLingua-2 PromptCompressor 초기화)
#       -> Step 3 (POST /compress 요청 수신) -> Step 4 (동적 rate 선택)
#       -> Step 5 (compress_prompt 호출 + dynamic_context_compression_ratio) -> Step 6 (압축된 텍스트 반환)]
# LLMLingua-2 프롬프트 압축 마이크로서비스.
# Node.js AI 백엔드가 도구 결과 JSON이 임계값을 초과할 때 이 서비스에 압축을 요청한다.
# 모델: microsoft/llmlingua-2-bert-base-multilingual-cased-meetingbank (다국어 지원, 경량)
#
# [Flow: OpenVINO INT8 가속 — CPU 추론 속도 2~4x 향상]
# 변환 스크립트(convert_to_openvino.py)가 빌드 시 모델을 OpenVINO INT8 형식으로 변환한다.
# 런타임은 OpenVINO 모델을 우선 로드하고, 실패 시 PyTorch 모델로 폴백한다.
import logging
import os
import time
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("llmlingua-service")

app = FastAPI(title="LLMLingua-2 Compression Service", version="3.0.0")

# [Flow: 모델 이름 환경변수 — 기본값은 다국어 BERT 기반 경량 모델]
MODEL_NAME = os.environ.get("LLMLINGUA_MODEL", "microsoft/llmlingua-2-bert-base-multilingual-cased-meetingbank")

# [Flow: OpenVINO INT8 모델 경로 — 변환 스크립트가 빌드 시 생성]
OV_INT8_DIR = os.environ.get("LLMLINGUA_OV_MODEL_DIR", "/app/ov_model_int8")

# [Flow: fallback 압축 비율 — 동적 선택 실패 시 사용 (기본 0.5 = 2x 압축)]
FALLBACK_RATE = float(os.environ.get("LLMLINGUA_RATE", "0.5"))

# [Flow: 동적 압축 임계값 — 도구 결과 크기(문자 수)에 따라 rate 를 3단계로 선택]
#   4000~8000자  → rate=0.5 (2x 압축, 정보 밀도 높음, 성능 손실 ~5%)
#   8000~20000자 → rate=0.3 (3x 압축, 중간 영역, 성능 손실 ~7%)
#   20000자 초과 → rate=0.2 (5x 압축, 대용량, 성능 손실 ~11%, 토큰 80% 절약)
# 근거: LLMLingua-2 논문 Table 5/6/12, Appendix L (Sample-Wise Dynamic Compression Ratio)
DYNAMIC_RATE_TIERS = [
    (8000, 0.5),    # 4000~8000자: 보수적 압축
    (20000, 0.3),   # 8000~20000자: 중간 압축
    (float("inf"), 0.2),  # 20000자 초과: 공격적 압축
]

# [Flow: 도구 결과 JSON의 핵심 키 — force_tokens 로 지정하여 압축 시 보존]
# 좌표/ID/페이지/색상/타입 등 구조적 정보 손실 방지
FORCE_TOKENS = ["error", "id", "page", "bbox", "rect", "color", "contents", "type"]

# [Flow: 문맥별 동적 압축 비율 — 논문 Appendix L 의 sample-wise DCR 방식]
# 0.4 = 각 문맥(청크)마다 최대 40% 가변 허용하여 정보 밀도에 맞춤
DYNAMIC_CONTEXT_COMPRESSION_RATIO = 0.4


def _createOpenVINOCompressor():
    """[Flow: Step 1 (OpenVINO 모델 로드) -> Step 2 (PromptCompressor 서브클래스 생성)
           -> Step 3 (resize_token_embeddings no-op 패치) -> Step 4 (compressor 반환)]

    OpenVINO INT8 양자화된 모델을 사용하는 PromptCompressor 인스턴스를 생성한다.
    변환 시 어휘가 미리 확장되었으므로 init_llmlingua2 의 resize_token_embeddings 를 no-op 로 만든다.

    @returns PromptCompressor 인스턴스 (OpenVINO 백엔드 사용)
    @raises ImportError optimum-intel 이 설치되지 않은 경우
    @raises FileNotFoundError OpenVINO 모델 디렉토리가 없는 경우
    """
    from optimum.intel import OVModelForTokenClassification
    from transformers import AutoConfig, AutoTokenizer
    from llmlingua import PromptCompressor

    # [Flow: OpenVINO INT8 모델 로드 — CPU 프로바이더 사용]
    logger.info(f"[openvino] Loading OpenVINO INT8 model from {OV_INT8_DIR}")
    ov_model = OVModelForTokenClassification.from_pretrained(OV_INT8_DIR)

    # [Flow: resize_token_embeddings no-op 패치]
    # 변환 스크립트가 이미 어휘를 확장했으므로 런타임에 재확장 불필요.
    # OpenVINO 모델은 고정된 그래프이므로 임베딩 크기 변경이 불가능하다.
    ov_model.resize_token_embeddings = lambda n: None

    # [Flow: 토크나이저 + config 로드 — OpenVINO 모델 디렉토리에서 함께 로드]
    config = AutoConfig.from_pretrained(OV_INT8_DIR)
    tokenizer = AutoTokenizer.from_pretrained(OV_INT8_DIR)
    tokenizer.padding_side = "left"
    tokenizer.pad_token_id = config.pad_token_id if config.pad_token_id else tokenizer.eos_token_id

    # [Flow: PromptCompressor 인스턴스 생성 후 모델 교체]
    # 먼저 더미 모델로 __init__ 을 호출한 후 self.model 을 OpenVINO 모델로 교체한다.
    # use_llmlingua2=True 시 init_llmlingua2() 가 호출되는데,
    # 이 시점에서는 ov_model.resize_token_embeddings 가 no-op 이므로 안전하다.
    compressor = PromptCompressor(
        model_name=MODEL_NAME,
        use_llmlingua2=True,
        device_map="cpu",
    )
    # [Flow: PyTorch 모델을 OpenVINO 모델로 교체]
    compressor.model = ov_model
    compressor.device = "cpu"

    logger.info("[openvino] OpenVINO INT8 model loaded successfully")
    return compressor


def _createPyTorchCompressor():
    """[Flow: PyTorch 폴백 — OpenVINO 모델을 사용할 수 없을 때 원본 PyTorch 모델 사용]

    @returns PromptCompressor 인스턴스 (PyTorch 백엔드 사용)
    """
    from llmlingua import PromptCompressor

    logger.info(f"[pytorch] Fallback to PyTorch model: {MODEL_NAME}")
    compressor = PromptCompressor(
        model_name=MODEL_NAME,
        use_llmlingua2=True,
        device_map="cpu",
    )
    logger.info("[pytorch] PyTorch model loaded successfully")
    return compressor


# [Flow: 서버 시작 시 PromptCompressor 인스턴스 생성 — OpenVINO 우선, PyTorch 폴백]
logger.info(f"Initializing LLMLingua-2 with model: {MODEL_NAME}")
_start = time.time()

_use_openvino = os.path.isdir(OV_INT8_DIR) and os.path.exists(f"{OV_INT8_DIR}/openvino_model.xml")

if _use_openvino:
    try:
        compressor = _createOpenVINOCompressor()
    except Exception as e:
        logger.warning(f"[openvino] Failed to load OpenVINO model: {e}, falling back to PyTorch")
        compressor = _createPyTorchCompressor()
else:
    logger.info(f"[openvino] OpenVINO model not found at {OV_INT8_DIR}, using PyTorch")
    compressor = _createPyTorchCompressor()

_elapsed = time.time() - _start
logger.info(f"LLMLingua-2 loaded in {_elapsed:.1f}s")


def _selectDynamicRate(text_len: int) -> float:
    """[Flow: Step 1 (텍스트 길이 수신) -> Step 2 (임계값 티어 매칭) -> Step 3 (해당 rate 반환)]

    도구 결과 크기(문자 수)에 따라 동적 압축 비율을 선택한다.
    논문 Appendix L 의 Sample-Wise Dynamic Compression Ratio 방식 적용.

    @param text_len 압축 대상 텍스트 길이 (문자 수)
    @returns 압축 비율 (0.0~1.0, 낮을수록 더 압축)
    """
    for threshold, rate in DYNAMIC_RATE_TIERS:
        if text_len <= threshold:
            return rate
    return DYNAMIC_RATE_TIERS[-1][1]


class CompressRequest(BaseModel):
    """압축 요청 본문."""

    text: str = Field(..., description="압축할 텍스트 (도구 결과 JSON 등)")
    rate: float = Field(default=-1.0, description="고정 압축 비율 (-1이면 동적 선택, 0.0~1.0)")
    target_token: int = Field(default=-1, description="목표 토큰 수 (-1이면 rate 사용)")
    dynamic: bool = Field(default=True, description="동적 rate 선택 사용 여부 (기본 True)")


class CompressResponse(BaseModel):
    """압축 응답."""

    compressed: str
    original_length: int
    compressed_length: int
    reduction_percent: float
    applied_rate: float
    elapsed_ms: float


@app.get("/health")
async def health() -> dict[str, str]:
    """헬스체크 엔드포인트."""
    backend = "openvino-int8" if _use_openvino else "pytorch"
    return {"status": "ok", "model": MODEL_NAME, "backend": backend}


@app.post("/compress", response_model=CompressResponse)
async def compress(req: CompressRequest) -> CompressResponse:
    """[Flow: Step 1 (텍스트 수신) -> Step 2 (동적 rate 선택 또는 고정 rate 사용)
           -> Step 3 (compress_prompt 호출 + force_tokens + dynamic_context_compression_ratio)
           -> Step 4 (압축 결과 반환)]

    LLMLingua-2 로 텍스트를 압축한다. 도구 결과 JSON이 임계값을 초과할 때 호출된다.
    dynamic=True 시 텍스트 크기에 따라 rate 가 자동 선택된다 (논문 Appendix L 방식).
    실패 시 원본 텍스트를 그대로 반환한다 (폴백).
    """
    original_length = len(req.text)
    _start = time.time()

    # [Flow: Step 2 — 동적 rate 선택 또는 요청된 고정 rate 사용]
    if req.dynamic and req.rate < 0:
        applied_rate = _selectDynamicRate(original_length)
    else:
        applied_rate = req.rate if req.rate >= 0 else FALLBACK_RATE

    try:
        result = compressor.compress_prompt(
            context=[req.text],
            rate=applied_rate,
            target_token=req.target_token,
            # [Flow: 도구 결과 핵심 JSON 키 보존 — 좌표/ID/페이지/색상 손실 방지]
            force_tokens=FORCE_TOKENS,
            force_reserve_digit=True,
            drop_consecutive=True,
            # [Flow: 문맥별 동적 압축 — 논문 Appendix L sample-wise DCR]
            dynamic_context_compression_ratio=DYNAMIC_CONTEXT_COMPRESSION_RATIO,
        )
        compressed = result.get("compressed_prompt", req.text)
        elapsed_ms = (time.time() - _start) * 1000
        compressed_length = len(compressed)
        reduction = (1 - compressed_length / original_length) * 100 if original_length > 0 else 0

        logger.info(
            f"compressed: {original_length} -> {compressed_length} chars "
            f"({reduction:.1f}% reduction, rate={applied_rate}, {elapsed_ms:.0f}ms)"
        )

        return CompressResponse(
            compressed=compressed,
            original_length=original_length,
            compressed_length=compressed_length,
            reduction_percent=round(reduction, 1),
            applied_rate=applied_rate,
            elapsed_ms=round(elapsed_ms, 1),
        )
    except Exception as e:
        logger.error(f"compression failed: {e}", exc_info=True)
        elapsed_ms = (time.time() - _start) * 1000
        # [Flow: 폴백 — 압축 실패 시 원본 반환]
        return CompressResponse(
            compressed=req.text,
            original_length=original_length,
            compressed_length=original_length,
            reduction_percent=0.0,
            applied_rate=applied_rate,
            elapsed_ms=round(elapsed_ms, 1),
        )
