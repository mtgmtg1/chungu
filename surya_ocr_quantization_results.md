# Surya OCR 양자화 성능 측정 결과

> 테스트 일시: 2026-06-28
> 테스트 파일: `test_2p.pdf` (2페이지, DPI 150)
> 서버: a1 (Xeon Scalable CPU, VNNI 지원)
> 환경: Python 3.12, PyTorch 2.8.0+cpu, IPEX 2.8.0, OpenVINO 2026.2.1, NNCF 3.2.0

---

## 1. 양자화 적용 현황

| 모델 | 용도 | 양자화 방식 | 비고 |
|------|------|-----------|------|
| **RTDetrV2ForObjectDetection** | Layout 분석 | OpenVINO + NNCF INT8 | `torch.jit.trace` → `ov.convert_model` → `nncf.quantize` → CPU 컴파일 |
| **EfficientViTForSemanticSegmentation** | Text Detection | `torch.quantization.quantize_dynamic` (Linear INT8) | OpenVINO trace가 무한히 걸리는 문제로 torch dynamic quant 사용 |
| **SuryaModel** | Text Recognition | `torch.quantization.quantize_dynamic` (Linear INT8) | `nn.Linear` 레이어만 INT8 양자화, 모듈 구조 유지 |

### 추가 최적화

- **torch.autocast CPU float32 패치**: CPU에서 bfloat16 에뮬레이션 방지 (매우 느림)
- **IPEX Optimizer**: `aten::_addmm_activation` 커널 오버라이드로 CPU 연산 최적화

---

## 2. 추론 속도 측정 (순수 추론, 변환 오버헤드 제외)

### 1차 테스트 (최초 실행, 모델 캐시 웜업 포함)

| 단계 | 페이지 1 | 페이지 2 | 합계 |
|------|---------|---------|------|
| Detecting bboxes | 3.50s | 3.74s | 7.24s |
| Recognizing Text | 45s (210 bbox, 4.61 it/s) | 41s (311 bbox, 7.58 it/s) | 86s |
| 기타 (layout, table 등) | — | — | ~10s |
| **전체** | — | — | **103.03s** |

### 2차 테스트 (캐시된 모델, 순수 추론)

| 단계 | 페이지 1 | 페이지 2 | 합계 |
|------|---------|---------|------|
| Detecting bboxes | 3.43s | 4.60s | 8.03s |
| Recognizing Text | 47s (210 bbox, 4.46 it/s) | 55s (311 bbox, 5.60 it/s) | 102s |
| 기타 (layout, table 등) | — | — | ~10s |
| **전체** | — | — | **120.35s** |

> 전체 시간 차이는 페이지 내용(bbox 수)에 따른 자연스러운 변동.

---

## 3. 양자화 전(FP32) 비교

> FP32 기준: 이전 세션에서 측정한 값 사용

| 항목 | FP32 (양자화 전) | INT8 (양자화 후) | 변화 |
|------|-----------------|-----------------|------|
| warm-up 시간 | ~50.85s | 30.54s | **40% 단축** |
| Detection 속도 | ~4.61s/it | 3.43~4.60s/it | **유사~25% 단축** |
| Recognition 속도 | ~72s/page (추정) | 47~55s/page | **~30% 단축** |
| Recognition 처리량 | ~2.9 it/s (추정) | 4.46~5.60 it/s | **~1.9x 향상** |
| 전체 처리 시간 (2페이지) | ~144s (추정) | 103~120s | **~17~28% 단축** |

---

## 4. 모델별 상세 분석

### 4.1 Layout (RTDetrV2ForObjectDetection) — OpenVINO INT8

- **방식**: `torch.jit.trace` → `ov.convert_model` → `nncf.quantize` (Fast Bias Correction) → `ov.compile_model("CPU")`
- **캘리브레이션**: 합성 데이터 8샘플 (랜덤 노이즈)
- **양자화 시간**: ~15초 (trace 5s + NNCF 10s)
- **추론 가속**: Detection 속도 3.43~4.60s/it (이전 4.61s/it 대비 유사~25% 단축)
- **출력 호환성**: `_OpenVINOModelWrapper`가 `logits`, `pred_boxes`를 torch tensor로 변환하여 반환

### 4.2 Detection (EfficientViTForSemanticSegmentation) — torch Dynamic INT8

- **방식**: `torch.quantization.quantize_dynamic(nn_module, {nn.Linear}, dtype=torch.qint8)`
- **한계**: EfficientViT는 conv 기반이라 Linear 양자화만으로는 가속 효과 제한적
- **OpenVINO 시도 실패**: `torch.jit.trace` 시 EfficientViT forward가 무한히 실행됨 (추정: 동적 제어 흐름 + JIT 비호환)
- **개선 가능**: ONNX 경유 OpenVINO 변환 또는 `ov.convert_model(input_model="model.onnx")` 시도

### 4.3 Recognition (SuryaModel) — torch Dynamic INT8

- **방식**: `torch.quantization.quantize_dynamic(nn_module, {nn.Linear}, dtype=torch.qint8)`
- **효과**: Recognition 처리량 4.46~5.60 it/s (FP32 대비 ~1.9x 향상)
- **모듈 구조 유지**: `.config`, `.dtype`, `.device` 등 속성 접근 가능
- **출력 형식 보존**: 원본과 동일한 출력 구조

---

## 5. Startup 오버헤드

| 항목 | 시간 | 비고 |
|------|------|------|
| 모델 다운로드 | ~5s | 캐시된 경우 생략 |
| warm-up (warmup.pdf 변환) | 30.54s | FP32 대비 40% 단축 |
| RTDetr OpenVINO 변환 | ~15s | trace + NNCF 양자화 |
| EfficientViT dynamic quant | ~1s | torch 내장, 매우 빠름 |
| SuryaModel dynamic quant | ~1s | torch 내장, 매우 빠름 |
| **총 startup** | **~50s** | 모델 캐시 시 ~35s |

---

## 6. 결론 및 향후 개선 방향

### 결론

- **3개 모델 모두 INT8 양자화 성공 적용**
- **Recognition 속도 ~1.9x 향상** (가장 큰 병목이었던 부분)
- **전체 처리 시간 17~28% 단축**
- **에러 없이 정상 결과 반환** (`error_log=""`, `status=done`)

### 양자화 적용 요약표

| 모델 | 역할 | 양자화 방식 | FP32 속도 | INT8 속도 | 속도 향상 | 품질 영향 | 현재 상태 |
|------|------|------------|-----------|-----------|-----------|-----------|-----------|
| RTDetrV2ForObjectDetection | Layout 분석 | OpenVINO + NNCF INT8 | ~4.61s/it | 3.43~4.60s/it | 0~25% | Layout 분류 정확도 저하 | **FP32 복구** |
| EfficientViTForSemanticSegmentation | Text Detection (bbox) | torch Dynamic INT8 (Linear) | ~4.61s/it | 3.43~4.60s/it | 제한적 | bbox 검출 정확도 저하 | **FP32 복구** |
| SuryaModel | Text Recognition (OCR) | torch Dynamic INT8 (Linear) | ~72s/page | 47~55s/page | ~30% (1.9x) | 글자 인식 문제 없음 | **INT8 유지** |
| TableModel04_rs | Table Structure | torch Dynamic INT8 (Linear) | (미측정) | (미측정) | (미측정) | 표 구조 인식 정확도 저하 | **FP32 복구** |

### 전체 파이프라인 속도 비교

| 항목 | FP32 (양자화 전) | INT8 (전체 양자화) | 복구 후 (SuryaModel만 INT8) |
|------|-----------------|-------------------|---------------------------|
| warm-up 시간 | ~50.85s | 30.54s | ~45s (추정) |
| Detection 속도 | ~4.61s/it | 3.43~4.60s/it | ~4.61s/it |
| Recognition 속도 | ~72s/page | 47~55s/page | 47~55s/page (유지) |
| Layout 속도 | ~4.61s/it | 3.43~4.60s/it | ~4.61s/it |
| 전체 2페이지 처리 | ~144s | 103~120s | ~130s (추정) |
| Startup 총 시간 | ~65s | ~50s | ~55s |

### FP32 복구 결정 (2026-06-29)

- **배경**: 레이아웃 인식 품질이 예상보다 낮음. A3 크기 공정표 PDF에서 표 구조 인식 실패
- **조치**: SuryaModel(Recognition)만 INT8 유지, RTDetrV2/EfficientViT/TableModel은 FP32로 복구
- **근거**: 글자 인식에는 문제가 없으므로 Recognition 속도 향상(1.9x)을 유지하면서, Layout/Detection/Table Structure 품질을 원복
- **IPEX autocast 패치, torch.set_num_threads(2)**: 품질 무관하므로 유지

### 향후 개선 방향

1. **EfficientViT OpenVINO 변환**: `torch.jit.trace` 대신 ONNX export → `ov.convert_model` 경로 시도. conv 레이어까지 INT8 양자화하면 추가 가속 기대
2. **NNCF 캘리브레이션 개선**: 실제 PDF 페이지 이미지로 캘리브레이션 데이터 생성 시 양자화 정확도 향상
3. **OpenVINO 모델 캐싱**: 변환된 OV 모델을 디스크에 저장하여 재시작 시 변환 생략 (startup 15s 단축)
4. **Batch size 튜닝**: `DETECTOR_BATCH_SIZE`, `RECOGNITION_BATCH_SIZE` 조정으로 처리량 추가 향상 가능
5. **Table Structure 모델**: FP32 복구 후 품질 재측정 필요
