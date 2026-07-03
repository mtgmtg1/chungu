---
sidebar_position: 4
---

# 모델 및 파이프라인

PROOF는 입력 유형, 정확도 요구 사항, 예산에 따라 두 가지 처리 모델을 제공합니다.

## 기본 모델 (`ocr_model=basic`)

기본 모델은 텍스트 레이어가 있는 PDF에 Docling을 사용하고, 스캔 문서 및 이미지에 Tesseract OCR을 사용합니다. 비용 효율적이고 빠릅니다.

- **적합**: 텍스트가 포함된 깨끗한 디지털 PDF
- **속도**: 빠름 — LLM 호출 없이 텍스트 추출
- **비용**: 페이지당 $0.001 (1 milli-USD), **하루 100페이지 무료**
- **제한 사항**: 오디오/비디오 미지원, 복잡한 레이아웃에서 정확도 낮음

```bash
curl -X POST https://your-domain.com/api/v1/jobs/upload \
  -H "X-API-Key: chu_live_xxxxxxxx" \
  -F "files=@document.pdf" \
  -F "ocr_model=basic"
```

## 고급 모델 (`ocr_model=premium`)

고급 모델은 모든 페이지에 high performance AI(26B) 비전 모델을 사용하여 복잡한 문서, 스캔 이미지, 손글씨, 회전된 페이지, 표에서 뛰어난 정확도를 제공합니다.

- **적합**: 스캔 문서, 손글씨, 복잡한 표, 이미지, 오디오/비디오
- **속도**: 보통 — 페이지당 1회 LLM 호출
- **비용**: 페이지당 $0.005 (5 milli-USD), 무료 한도 없음
- **기능**: 오디오 ($0.001/초), 비디오 ($0.005/초), Docling 정제 옵션

```bash
curl -X POST https://your-domain.com/api/v1/jobs/upload \
  -H "X-API-Key: chu_live_xxxxxxxx" \
  -F "files=@document.pdf" \
  -F "ocr_model=premium"
```

## OCR 엔진 선택

고급 모델의 경우 텍스트 추출에 사용할 OCR 엔진을 지정할 수 있습니다:

| 엔진 | 플래그 | 비고 |
|--------|------|-------|
| `easyocr` | 기본값 | 속도와 정확도의 균형 |
| `tesseract` | `ocr_engine=tesseract` | 빠르고 광범위하게 지원됨 |
| `rapidocr` | `ocr_engine=rapidocr` | CJK 텍스트에 최적화 |

```bash
curl -X POST https://your-domain.com/api/v1/jobs/upload \
  -H "X-API-Key: chu_live_xxxxxxxx" \
  -F "files=@document.pdf" \
  -F "ocr_model=premium" \
  -F "ocr_engine=rapidocr"
```

## 모델 선택

| 시나리오 | 권장 모델 |
|----------|-------------------|
| 텍스트 레이어가 있는 깨끗한 디지털 PDF | `basic` |
| 스캔 문서 | `premium` |
| 손글씨 | `premium` |
| 표가 있는 이미지 | `premium` |
| 오디오/비디오 | `premium` (필수) |
| 예산 중심, 대용량 | `basic` (하루 100페이지 무료) |
