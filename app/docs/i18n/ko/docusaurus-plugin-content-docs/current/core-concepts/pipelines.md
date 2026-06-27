---
sidebar_position: 4
---

# 파이프라인

Chungu는 입력 유형과 정확도 요구 사항에 따라 두 가지 처리 파이프라인을 제공합니다.

## Vision 파이프라인 (기본)

`vision` 파이프라인은 각 PDF 페이지를 이미지로 렌더링하고 비전 언어 모델(VLM)에 전송하여 직접 표를 추출합니다.

- **적합**: 깨끗한 PDF, 스캔 문서, 이미지
- **속도**: 빠름 — 페이지당 1회 모델 호출
- **정확도**: 구조화된 표에 높음

```bash
curl -X POST https://your-domain.com/api/v1/jobs/upload \
  -H "X-API-Key: chu_live_xxxxxxxx" \
  -F "files=@document.pdf" \
  -F "pipeline=vision"
```

## 하이브리드 파이프라인

`hybrid` 파이프라인은 OCR 텍스트 추출과 비전 모델 분석을 결합합니다. 먼저 Tesseract OCR로 텍스트를 추출한 후, 이미지와 OCR 텍스트를 모두 모델에 전송합니다.

- **적합**: 텍스트와 표가 혼합된 문서, 저품질 스캔
- **속도**: 느림 — 페이지당 OCR + 모델 호출
- **정확도**: 복잡한 레이아웃의 텍스트 중심 문서에 더 높음

```bash
curl -X POST https://your-domain.com/api/v1/jobs/upload \
  -H "X-API-Key: chu_live_xxxxxxxx" \
  -F "files=@document.pdf" \
  -F "pipeline=hybrid"
```

## 파이프라인 선택

| 시나리오 | 권장 파이프라인 |
|----------|---------------------|
| 깨끗한 디지털 PDF | `vision` |
| 스캔 문서 | `vision` |
| 텍스트가 있는 저품질 스캔 | `hybrid` |
| 표가 있는 이미지 | `vision` |
| 오디오/비디오 | 어느 쪽이든 (미디어에는 파이프라인이 무시됨) |
