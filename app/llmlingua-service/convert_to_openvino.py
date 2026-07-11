#!/usr/bin/env python3
# [Flow: Step 1 (HF 모델 로드 + 어휘 확장) -> Step 2 (OpenVINO FP32 변환)
#       -> Step 3 (NNCF INT8 양자화 + 캘리브레이션) -> Step 4 (양자화된 모델 저장)]
# LLMLingua-2 BERT 모델을 OpenVINO INT8 형식으로 변환한다.
# CPU 추론 속도를 높이기 위해 가중치 + 활성화 INT8 양자화를 적용한다.
# Docker 빌드 시 한 번 실행되어 변환된 모델을 이미지에 포함한다.

import os
import torch
from transformers import AutoModelForTokenClassification, AutoTokenizer, AutoConfig

# [Flow: 환경변수 — 기본값은 다국어 BERT 기반 LLMLingua-2 경량 모델]
MODEL_NAME = os.environ.get("LLMLINGUA_MODEL", "microsoft/llmlingua-2-bert-base-multilingual-cased-meetingbank")
MAX_FORCE_TOKEN = 100
EXPANDED_DIR = "/app/expanded_model"
OV_FP32_DIR = "/app/ov_model_fp32"
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
    print(f"[convert] Saved expanded model to {EXPANDED_DIR}")

    # [Flow: Step 2 — OpenVINO FP32 형식으로 변환]
    # optimum-intel 의 OVModelForTokenClassification 로 PyTorch → OpenVINO IR 변환
    from optimum.intel import OVModelForTokenClassification

    print(f"[convert] Exporting to OpenVINO FP32...")
    ov_model = OVModelForTokenClassification.from_pretrained(EXPANDED_DIR, export=True)
    ov_model.save_pretrained(OV_FP32_DIR)
    print(f"[convert] Saved OpenVINO FP32 model to {OV_FP32_DIR}")

    # [Flow: Step 3 — NNCF INT8 양자화 (Post-Training Quantization)]
    # 가중치 + 활성화 모두 INT8 로 양자화하여 CPU 추론 속도를 2~4x 향상
    # 캘리브레이션 데이터로 50개 샘플 문장을 사용하여 활성화 분포 추정
    import nncf
    from openvino import Core, serialize

    print(f"[convert] Applying INT8 quantization with NNCF...")
    core = Core()
    ov_model_raw = core.read_model(f"{OV_FP32_DIR}/openvino_model.xml")

    # [Flow: 캘리브레이션 데이터셋 — 도구 결과 JSON과 유사한 분포의 샘플 문장]
    # LLMLingua-2 가 실제로 처리하는 도구 결과(annotations, sandbox, spreadsheet 등)와
    # 유사한 패턴의 텍스트를 사용하여 양자화 정확도를 높인다
    calibration_texts = [
        "This is a test sentence for calibration of the LLMLingua-2 compression model.",
        "Another example sentence for quantization calibration with various words.",
        "The quick brown fox jumps over the lazy dog in the park near the river.",
        "Lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod tempor.",
        "Machine learning models can be quantized to reduce inference latency on CPU.",
        "PDF annotation extraction involves bounding boxes coordinates and page numbers.",
        "Spreadsheet data contains rows columns cells with numeric and text values.",
        "Document analysis requires understanding of layout structure and content.",
        "Token classification models predict labels for each token in the input.",
        "Prompt compression reduces token count while preserving essential information.",
        "The agent received tool results containing error messages and stack traces.",
        "Sandbox execution completed with exit code 0 and stdout output 2000 characters.",
        "Browserless web extraction returned 3000 characters of text content from page.",
        "Annotations array contains 20 elements with id page bbox rect color type keys.",
        "Job JSON metadata includes source type approval mode and processing status.",
    ] * 4  # 60 samples

    encodings = tokenizer(
        calibration_texts,
        truncation=True,
        max_length=512,
        padding="max_length",
        return_tensors="np",
    )

    def transform_fn(sample_idx):
        """[Flow: 캘리브레이션 샘플을 OpenVINO 입력 형식으로 변환]

        OpenVINO 모델 입력은 2D (batch_size x seq_len) 형식이 필요하므로
        캘리브레이션 샘플에 batch 차원을 추가한다.

        @param sample_idx 캘리브레이션 데이터셋 인덱스
        @returns OpenVINO 모델 입력 딕셔너리 (input_ids, attention_mask)
        """
        import numpy as np
        return {
            "input_ids": np.expand_dims(encodings["input_ids"][sample_idx], axis=0),
            "attention_mask": np.expand_dims(encodings["attention_mask"][sample_idx], axis=0),
        }

    calibration_dataset = nncf.Dataset(range(len(calibration_texts)), transform_fn)
    quantized_model = nncf.quantize(ov_model_raw, calibration_dataset)

    # [Flow: Step 4 — 양자화된 모델 저장]
    # openvino_model.xml + openvino_model.bin 형식으로 저장
    # 런타임에 OVModelForTokenClassification.from_pretrained() 로 로드
    os.makedirs(OV_INT8_DIR, exist_ok=True)
    serialize(quantized_model, f"{OV_INT8_DIR}/openvino_model.xml")
    tokenizer.save_pretrained(OV_INT8_DIR)
    config.save_pretrained(OV_INT8_DIR)
    print(f"[convert] Saved OpenVINO INT8 model to {OV_INT8_DIR}")

    # 파일 크기 비교 출력
    fp32_size = os.path.getsize(f"{OV_FP32_DIR}/openvino_model.bin") / (1024 * 1024)
    int8_size = os.path.getsize(f"{OV_INT8_DIR}/openvino_model.bin") / (1024 * 1024)
    print(f"[convert] FP32 model size: {fp32_size:.1f} MB")
    print(f"[convert] INT8 model size: {int8_size:.1f} MB")
    print(f"[convert] Size reduction: {(1 - int8_size / fp32_size) * 100:.1f}%")
    print(f"[convert] Done!")


if __name__ == "__main__":
    main()
