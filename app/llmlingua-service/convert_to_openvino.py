#!/usr/bin/env python3
# [Flow: Step 1 (HF 모델 로드 + 어휘 확장) -> Step 2 (OpenVINO INT8 가중치 양자화 변환)
#       -> Step 3 (양자화된 모델 저장)]
# LLMLingua-2 BERT 모델을 OpenVINO INT8 형식으로 변환한다.
# CPU 추론 속도를 높이기 위해 가중치 INT8 양자화를 적용한다 (OVWeightQuantizationConfig).
# 가중치 전용 양자화는 캘리브레이션 불필요, BERT 동적 shape에서 안정적 작동.
# Docker 빌드 시 한 번 실행되어 변환된 모델을 이미지에 포함한다.

import os
import torch
from transformers import AutoModelForTokenClassification, AutoTokenizer, AutoConfig

# [Flow: 환경변수 — 기본값은 다국어 BERT 기반 LLMLingua-2 경량 모델]
MODEL_NAME = os.environ.get("LLMLINGUA_MODEL", "microsoft/llmlingua-2-bert-base-multilingual-cased-meetingbank")
MAX_FORCE_TOKEN = 100
EXPANDED_DIR = "/app/expanded_model"
OV_INT8_DIR = "/app/ov_model_int8"


def main():
    # [Flow: Step 1 — HF 모델 + 토크나이저 로드 후 어휘 확장]
    # PromptCompressor.init_llmlingua2() 가 [NEW0]..[NEW99] 특수 토큰을 추가하고
    # resize_token_embeddings() 를 호출하는데, OpenVINO 모델은 임베딩 크기를
    # 동적으로 변경할 수 없으므로 변환 시 미리 어휘를 확장한다.
    print(f"[convert] Loading model: {MODEL_NAME}")
    config = AutoConfig.from_pretrained(MODEL_NAME)
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    model = AutoModelForTokenClassification.from_pretrained(MODEL_NAME, torch_dtype=torch.float32)

    # [Flow: 어휘 확장 — LLMLingua-2 의 force_tokens 기능을 위한 100개 특수 토큰 추가]
    added_tokens = [f"[NEW{i}]" for i in range(MAX_FORCE_TOKEN)]
    tokenizer.add_special_tokens({"additional_special_tokens": added_tokens})
    model.resize_token_embeddings(len(tokenizer))
    print(f"[convert] Expanded vocab to {len(tokenizer)} tokens")

    # 확장된 모델 저장 (OpenVINO 변환의 입력으로 사용)
    os.makedirs(EXPANDED_DIR, exist_ok=True)
    model.save_pretrained(EXPANDED_DIR)
    tokenizer.save_pretrained(EXPANDED_DIR)
    config.save_pretrained(EXPANDED_DIR)
    print(f"[convert] Saved expanded model to {EXPANDED_DIR}")

    # [Flow: Step 2 — OpenVINO INT8 가중치 양자화 변환]
    # optimum-intel 의 OVModelForTokenClassification 로 PyTorch → OpenVINO IR 변환 +
    # OVWeightQuantizationConfig 로 가중치 INT8 양자화 (캘리브레이션 불필요)
    from optimum.intel import OVModelForTokenClassification, OVWeightQuantizationConfig

    print(f"[convert] Exporting to OpenVINO INT8 (weight-only quantization)...")
    quantization_config = OVWeightQuantizationConfig(bits=8)
    ov_model = OVModelForTokenClassification.from_pretrained(
        EXPANDED_DIR,
        export=True,
        quantization_config=quantization_config,
    )

    # [Flow: Step 3 — 양자화된 모델 저장]
    # openvino_model.xml + openvino_model.bin 형식으로 저장
    # 런타임에 OVModelForTokenClassification.from_pretrained() 로 로드
    os.makedirs(OV_INT8_DIR, exist_ok=True)
    ov_model.save_pretrained(OV_INT8_DIR)
    tokenizer.save_pretrained(OV_INT8_DIR)
    config.save_pretrained(OV_INT8_DIR)
    print(f"[convert] Saved OpenVINO INT8 model to {OV_INT8_DIR}")

    # 파일 크기 출력
    int8_size = os.path.getsize(f"{OV_INT8_DIR}/openvino_model.bin") / (1024 * 1024)
    print(f"[convert] INT8 model size: {int8_size:.1f} MB")
    print(f"[convert] Done!")


if __name__ == "__main__":
    main()
